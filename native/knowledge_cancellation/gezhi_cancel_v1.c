#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>

#define GEZHI_PHASE_MASK UINT64_C(0x7)
#define GEZHI_LATCH_BIT UINT64_C(0x8)
#define GEZHI_GENERATION_SHIFT 4
#define GEZHI_GENERATION_MASK UINT64_C(0x0FFFFFFF)
#define GEZHI_TOKEN_SHIFT 32
#define GEZHI_MAX_GENERATION UINT64_C(0x0FFFFFFF)

#define GEZHI_PHASE_OUTSIDE UINT64_C(0)
#define GEZHI_PHASE_ARMED UINT64_C(1)
#define GEZHI_PHASE_ACCEPTING UINT64_C(2)
#define GEZHI_PHASE_SEALED UINT64_C(3)
#define GEZHI_PHASE_RELEASED UINT64_C(4)

static volatile LONG64 gezhi_control = 0;
static volatile LONG64 gezhi_observed_ns = 0;
static volatile LONG gezhi_publication_ready = 0;
static volatile LONG gezhi_admission_writers = 0;
static volatile LONG gezhi_accepted_in_flight = 0;
static volatile LONG gezhi_poisoned = 0;
static volatile LONG gezhi_registered = 0;
static LARGE_INTEGER gezhi_qpc_frequency = {0};

static LONG64 gezhi_load_control(void) {
    return InterlockedCompareExchange64(&gezhi_control, 0, 0);
}

static uint64_t gezhi_phase(uint64_t control) {
    return control & GEZHI_PHASE_MASK;
}

static uint64_t gezhi_generation(uint64_t control) {
    return (control >> GEZHI_GENERATION_SHIFT) & GEZHI_GENERATION_MASK;
}

static uint64_t gezhi_observation_ns(LARGE_INTEGER counter) {
    uint64_t ticks = (uint64_t)counter.QuadPart;
    uint64_t frequency = (uint64_t)gezhi_qpc_frequency.QuadPart;
    uint64_t seconds = ticks / frequency;
    uint64_t remainder = ticks % frequency;
    if (seconds > (UINT64_MAX / UINT64_C(1000000000))) {
        InterlockedExchange(&gezhi_poisoned, 1);
        return 0;
    }
    return seconds * UINT64_C(1000000000)
        + (remainder * UINT64_C(1000000000)) / frequency;
}

static BOOL WINAPI gezhi_handler(DWORD control_type) {
    uint64_t observed;
    uint64_t desired;
    uint64_t generation;
    BOOL first_observation;
    LARGE_INTEGER counter;

    if (control_type != CTRL_C_EVENT) {
        return FALSE;
    }
    InterlockedIncrement(&gezhi_admission_writers);
    for (;;) {
        observed = (uint64_t)gezhi_load_control();
        if (gezhi_phase(observed) != GEZHI_PHASE_ACCEPTING) {
            InterlockedDecrement(&gezhi_admission_writers);
            return FALSE;
        }
        generation = gezhi_generation(observed);
        if (generation == GEZHI_MAX_GENERATION) {
            InterlockedExchange(&gezhi_poisoned, 1);
            InterlockedDecrement(&gezhi_admission_writers);
            return TRUE;
        }
        first_observation = (observed & GEZHI_LATCH_BIT) == 0;
        desired = observed | GEZHI_LATCH_BIT;
        desired += UINT64_C(1) << GEZHI_GENERATION_SHIFT;
        if ((uint64_t)InterlockedCompareExchange64(
                &gezhi_control,
                (LONG64)desired,
                (LONG64)observed) == observed) {
            break;
        }
    }
    InterlockedIncrement(&gezhi_accepted_in_flight);
    if (first_observation) {
        if (!QueryPerformanceCounter(&counter) || counter.QuadPart < 0) {
            InterlockedExchange(&gezhi_poisoned, 1);
        } else {
            InterlockedExchange64(
                &gezhi_observed_ns,
                (LONG64)gezhi_observation_ns(counter));
            MemoryBarrier();
            InterlockedExchange(&gezhi_publication_ready, 1);
        }
    }
    InterlockedDecrement(&gezhi_accepted_in_flight);
    InterlockedDecrement(&gezhi_admission_writers);
    return TRUE;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_arm(void) {
    uint64_t expected = GEZHI_PHASE_OUTSIDE;
    uint64_t desired = GEZHI_PHASE_ARMED;

    if (gezhi_load_control() != (LONG64)expected
        || InterlockedCompareExchange(&gezhi_registered, 0, 0) != 0
        || !QueryPerformanceFrequency(&gezhi_qpc_frequency)
        || gezhi_qpc_frequency.QuadPart <= 0) {
        return 0;
    }
    if (!SetConsoleCtrlHandler(gezhi_handler, TRUE)) {
        return 0;
    }
    InterlockedExchange(&gezhi_registered, 1);
    if ((uint64_t)InterlockedCompareExchange64(
            &gezhi_control,
            (LONG64)desired,
            (LONG64)expected) != expected) {
        SetConsoleCtrlHandler(gezhi_handler, FALSE);
        InterlockedExchange(&gezhi_registered, 0);
        InterlockedExchange(&gezhi_poisoned, 1);
        return 0;
    }
    return 1;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_activate(void) {
    uint64_t expected = GEZHI_PHASE_ARMED;
    uint64_t desired = GEZHI_PHASE_ACCEPTING;
    return (uint64_t)InterlockedCompareExchange64(
        &gezhi_control,
        (LONG64)desired,
        (LONG64)expected) == expected;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_try_begin_work(void) {
    uint64_t control = (uint64_t)gezhi_load_control();
    return gezhi_phase(control) == GEZHI_PHASE_ACCEPTING
        && (control & GEZHI_LATCH_BIT) == 0;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_snapshot(
    uint32_t *phase,
    uint32_t *generation,
    int *latched,
    int64_t *observed_ns,
    uint32_t *accepted_in_flight,
    int *publication_ready,
    uint32_t *sealed_candidate_token) {
    int attempt;
    uint64_t first_control;
    uint64_t second_control;
    LONG first_in_flight;
    LONG second_in_flight;
    LONG ready;
    LONG64 observation;

    if (phase == NULL || generation == NULL || latched == NULL
        || observed_ns == NULL || accepted_in_flight == NULL
        || publication_ready == NULL || sealed_candidate_token == NULL) {
        return -1;
    }
    for (attempt = 0; attempt < 4096; ++attempt) {
        if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
            return -1;
        }
        first_control = (uint64_t)gezhi_load_control();
        first_in_flight = InterlockedCompareExchange(
            &gezhi_accepted_in_flight, 0, 0);
        ready = InterlockedCompareExchange(&gezhi_publication_ready, 0, 0);
        observation = InterlockedCompareExchange64(&gezhi_observed_ns, 0, 0);
        second_in_flight = InterlockedCompareExchange(
            &gezhi_accepted_in_flight, 0, 0);
        second_control = (uint64_t)gezhi_load_control();
        if (first_control != second_control
            || first_in_flight != second_in_flight
            || first_in_flight < 0) {
            YieldProcessor();
            continue;
        }
        if ((first_control & GEZHI_LATCH_BIT) != 0
            && (ready == 0 || observation < 0)) {
            YieldProcessor();
            continue;
        }
        *phase = (uint32_t)gezhi_phase(first_control);
        *generation = (uint32_t)gezhi_generation(first_control);
        *latched = (first_control & GEZHI_LATCH_BIT) != 0;
        *observed_ns = observation;
        *accepted_in_flight = (uint32_t)first_in_flight;
        *publication_ready = ready != 0;
        *sealed_candidate_token = (uint32_t)(first_control >> GEZHI_TOKEN_SHIFT);
        return 1;
    }
    return 0;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_conditional_seal(
    uint32_t expected_generation,
    uint32_t candidate_token) {
    uint64_t observed;
    uint64_t desired;

    if (candidate_token == 0 || expected_generation > GEZHI_MAX_GENERATION
        || InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return -1;
    }
    observed = (uint64_t)gezhi_load_control();
    if (gezhi_phase(observed) != GEZHI_PHASE_ACCEPTING
        || gezhi_generation(observed) != expected_generation) {
        return 0;
    }
    if ((observed & GEZHI_LATCH_BIT) != 0
        && InterlockedCompareExchange(&gezhi_publication_ready, 0, 0) == 0) {
        return 0;
    }
    if (InterlockedCompareExchange(&gezhi_admission_writers, 0, 0) != 0) {
        return 0;
    }
    desired = (observed & ~GEZHI_PHASE_MASK)
        | GEZHI_PHASE_SEALED
        | ((uint64_t)candidate_token << GEZHI_TOKEN_SHIFT);
    return (uint64_t)InterlockedCompareExchange64(
        &gezhi_control,
        (LONG64)desired,
        (LONG64)observed) == observed;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_release(void) {
    uint64_t observed;
    uint64_t desired;
    uint32_t attempt;

    observed = (uint64_t)gezhi_load_control();
    if (gezhi_phase(observed) != GEZHI_PHASE_SEALED
        || (observed >> GEZHI_TOKEN_SHIFT) == 0
        || InterlockedCompareExchange(&gezhi_registered, 0, 0) != 1) {
        return 0;
    }
    for (attempt = 0; attempt < 1000000; ++attempt) {
        if (InterlockedCompareExchange(&gezhi_accepted_in_flight, 0, 0) == 0) {
            break;
        }
        SwitchToThread();
    }
    if (InterlockedCompareExchange(&gezhi_accepted_in_flight, 0, 0) != 0
        || !SetConsoleCtrlHandler(gezhi_handler, FALSE)) {
        InterlockedExchange(&gezhi_poisoned, 1);
        return 0;
    }
    InterlockedExchange(&gezhi_registered, 0);
    desired = (observed & ~GEZHI_PHASE_MASK) | GEZHI_PHASE_RELEASED;
    if ((uint64_t)InterlockedCompareExchange64(
            &gezhi_control,
            (LONG64)desired,
            (LONG64)observed) != observed) {
        InterlockedExchange(&gezhi_poisoned, 1);
        return 0;
    }
    return 1;
}

#ifdef GEZHI_CANCEL_TESTING
__declspec(dllexport) int __stdcall gezhi_cancel_v1_test_dispatch(
    uint32_t control_type) {
    return gezhi_handler((DWORD)control_type) ? 1 : 0;
}
#endif
