#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <limits.h>
#include <stdint.h>

#define GEZHI_PHASE_MASK UINT64_C(0x7)
#define GEZHI_LATCH_BIT UINT64_C(0x8)
#define GEZHI_GENERATION_SHIFT 4
#define GEZHI_GENERATION_MASK UINT64_C(0x0FFFFFFF)
#define GEZHI_TOKEN_SHIFT 32
#define GEZHI_MAX_GENERATION UINT64_C(0x0FFFFFFF)
#define GEZHI_OBSERVER_CLOSED_BIT UINT64_C(0x8000000000000000)
#define GEZHI_OBSERVER_FAILED_BIT UINT64_C(0x4000000000000000)
#define GEZHI_OBSERVER_COUNT_MASK UINT64_C(0x3FFFFFFFFFFFFFFF)

#define GEZHI_PHASE_OUTSIDE UINT64_C(0)
#define GEZHI_PHASE_ARMED UINT64_C(1)
#define GEZHI_PHASE_ACCEPTING_PRE_ID UINT64_C(2)
#define GEZHI_PHASE_SEALED UINT64_C(3)
#define GEZHI_PHASE_RELEASED UINT64_C(4)
#define GEZHI_PHASE_ACCEPTING_POST_ID UINT64_C(5)

static volatile LONG64 gezhi_control = 0;
static volatile LONG64 gezhi_observed_ns = 0;
__declspec(align(8)) static volatile LONG64 gezhi_admission_observer_state = 0;
static volatile LONG gezhi_publication_ready = 0;
static volatile LONG gezhi_admission_gate = 0;
static volatile LONG gezhi_accepted_in_flight = 0;
static volatile LONG gezhi_poisoned = 0;
static volatile LONG gezhi_registered = 0;
static LARGE_INTEGER gezhi_qpc_frequency = {0};
#ifdef GEZHI_CANCEL_TESTING
static volatile LONG gezhi_test_poison_before_seal_gate = 0;
static volatile LONG gezhi_test_poison_before_seal_commit = 0;
static volatile LONG gezhi_test_seal_waiter_race_stage = 0;
#endif

static LONG64 gezhi_load_control(void) {
    return InterlockedCompareExchange64(&gezhi_control, 0, 0);
}

static uint64_t gezhi_phase(uint64_t control) {
    return control & GEZHI_PHASE_MASK;
}

static uint64_t gezhi_generation(uint64_t control) {
    return (control >> GEZHI_GENERATION_SHIFT) & GEZHI_GENERATION_MASK;
}

static BOOL gezhi_phase_is_accepting(uint64_t phase) {
    return phase == GEZHI_PHASE_ACCEPTING_PRE_ID
        || phase == GEZHI_PHASE_ACCEPTING_POST_ID;
}

static uint64_t gezhi_load_admission_observer_state(void) {
    return (uint64_t)InterlockedCompareExchange64(
        &gezhi_admission_observer_state, 0, 0);
}

static int gezhi_fail_admission_observer(void) {
    uint64_t previous = (uint64_t)InterlockedOr64(
        &gezhi_admission_observer_state,
        (LONG64)GEZHI_OBSERVER_FAILED_BIT);

    if ((previous & GEZHI_OBSERVER_CLOSED_BIT) != 0) {
        return 0;
    }
    InterlockedExchange(&gezhi_poisoned, 1);
    return -1;
}

static int gezhi_register_admission_observer(void) {
    uint64_t count;
    uint64_t desired;
    uint64_t observed;
    int attempt;

    for (attempt = 0; attempt < 4096; ++attempt) {
        observed = gezhi_load_admission_observer_state();
        if ((observed & GEZHI_OBSERVER_CLOSED_BIT) != 0) {
            return 0;
        }
        if ((observed & GEZHI_OBSERVER_FAILED_BIT) != 0) {
            InterlockedExchange(&gezhi_poisoned, 1);
            return -1;
        }
        count = observed & GEZHI_OBSERVER_COUNT_MASK;
        if (count == GEZHI_OBSERVER_COUNT_MASK) {
            return gezhi_fail_admission_observer();
        }
        desired = observed + UINT64_C(1);
        if ((uint64_t)InterlockedCompareExchange64(
                &gezhi_admission_observer_state,
                (LONG64)desired,
                (LONG64)observed) == observed) {
            return 1;
        }
        YieldProcessor();
    }
    return gezhi_fail_admission_observer();
}

static void gezhi_leave_admission_observer(void) {
    uint64_t count;
    uint64_t desired;
    uint64_t observed;
    int attempt;

    for (attempt = 0; attempt < 4096; ++attempt) {
        observed = gezhi_load_admission_observer_state();
        count = observed & GEZHI_OBSERVER_COUNT_MASK;
        if (count == 0) {
            InterlockedExchange(&gezhi_poisoned, 1);
            return;
        }
        desired = (observed & ~GEZHI_OBSERVER_COUNT_MASK) | (count - 1);
        if ((uint64_t)InterlockedCompareExchange64(
                &gezhi_admission_observer_state,
                (LONG64)desired,
                (LONG64)observed) == observed) {
            return;
        }
        YieldProcessor();
    }
    InterlockedExchange(&gezhi_poisoned, 1);
}

static int gezhi_try_enter_admission_gate(void) {
    LONG observed;
    int admission;
    int attempt;

    admission = gezhi_register_admission_observer();
    if (admission != 1) {
        return admission;
    }
    for (attempt = 0; attempt < 4096; ++attempt) {
        if ((gezhi_load_admission_observer_state()
                & GEZHI_OBSERVER_CLOSED_BIT) != 0) {
            admission = 0;
            break;
        }
        observed = InterlockedCompareExchange(&gezhi_admission_gate, 0, 0);
        if (observed < 0) {
            if (!gezhi_phase_is_accepting(
                    gezhi_phase((uint64_t)gezhi_load_control()))) {
                admission = 0;
                break;
            }
            YieldProcessor();
            continue;
        }
        if (observed == LONG_MAX) {
            admission = gezhi_fail_admission_observer();
            break;
        }
        if (InterlockedCompareExchange(
                &gezhi_admission_gate,
                observed + 1,
                observed) == observed) {
            admission = 1;
            break;
        }
        YieldProcessor();
    }
    if (attempt == 4096) {
#ifdef GEZHI_CANCEL_TESTING
        if (InterlockedCompareExchange(
                &gezhi_test_seal_waiter_race_stage, 3, 2) == 2) {
            while (InterlockedCompareExchange(
                    &gezhi_test_seal_waiter_race_stage, 0, 0) < 6) {
                YieldProcessor();
            }
        }
#endif
        admission = gezhi_fail_admission_observer();
#ifdef GEZHI_CANCEL_TESTING
        InterlockedCompareExchange(&gezhi_test_seal_waiter_race_stage, 7, 6);
#endif
    }
    gezhi_leave_admission_observer();
    return admission;
}

static int gezhi_drain_admission_observers(void) {
    uint64_t state;
    uint32_t attempt;

    for (attempt = 0; attempt < 1000000; ++attempt) {
        state = gezhi_load_admission_observer_state();
        if ((state & GEZHI_OBSERVER_COUNT_MASK) == 0) {
            return 1;
        }
        SwitchToThread();
    }
    InterlockedExchange(&gezhi_poisoned, 1);
    return 0;
}

static void gezhi_leave_admission_gate(void) {
    if (InterlockedDecrement(&gezhi_admission_gate) < 0) {
        InterlockedExchange(&gezhi_poisoned, 1);
    }
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
    LONG ready;
    LONG in_flight;
    int admission;
    int attempt;
    LARGE_INTEGER counter;

    if (control_type != CTRL_C_EVENT) {
        return FALSE;
    }
    admission = gezhi_try_enter_admission_gate();
    if (admission != 1) {
        return FALSE;
    }
    observed = (uint64_t)gezhi_load_control();
    if (!gezhi_phase_is_accepting(gezhi_phase(observed))) {
        gezhi_leave_admission_gate();
        return FALSE;
    }
    in_flight = InterlockedIncrement(&gezhi_accepted_in_flight);
    if (in_flight <= 0) {
        InterlockedExchange(&gezhi_poisoned, 1);
        gezhi_leave_admission_gate();
        return TRUE;
    }

    ready = InterlockedCompareExchange(&gezhi_publication_ready, -1, 0);
    if (ready == 0) {
        if (!QueryPerformanceCounter(&counter) || counter.QuadPart < 0) {
            InterlockedExchange(&gezhi_poisoned, 1);
        } else {
            InterlockedExchange64(
                &gezhi_observed_ns,
                (LONG64)gezhi_observation_ns(counter));
            MemoryBarrier();
            if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) == 0) {
                InterlockedExchange(&gezhi_publication_ready, 1);
            }
        }
    } else if (ready == -1) {
        for (attempt = 0; attempt < 4096; ++attempt) {
            ready = InterlockedCompareExchange(
                &gezhi_publication_ready, 0, 0);
            if (ready != -1) {
                break;
            }
            YieldProcessor();
        }
        if (ready != 1) {
            InterlockedExchange(&gezhi_poisoned, 1);
        }
    } else if (ready != 1) {
        InterlockedExchange(&gezhi_poisoned, 1);
    }

    for (;;) {
        if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
            InterlockedDecrement(&gezhi_accepted_in_flight);
            gezhi_leave_admission_gate();
            return TRUE;
        }
        observed = (uint64_t)gezhi_load_control();
        if (!gezhi_phase_is_accepting(gezhi_phase(observed))) {
            InterlockedExchange(&gezhi_poisoned, 1);
            InterlockedDecrement(&gezhi_accepted_in_flight);
            gezhi_leave_admission_gate();
            return TRUE;
        }
        generation = gezhi_generation(observed);
        if (generation == GEZHI_MAX_GENERATION) {
            InterlockedExchange(&gezhi_poisoned, 1);
            InterlockedDecrement(&gezhi_accepted_in_flight);
            gezhi_leave_admission_gate();
            return TRUE;
        }
        desired = observed | GEZHI_LATCH_BIT;
        desired += UINT64_C(1) << GEZHI_GENERATION_SHIFT;
        if ((uint64_t)InterlockedCompareExchange64(
                &gezhi_control,
                (LONG64)desired,
                (LONG64)observed) == observed) {
            break;
        }
    }
    InterlockedDecrement(&gezhi_accepted_in_flight);
    gezhi_leave_admission_gate();
    return TRUE;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_arm(void) {
    uint64_t expected = GEZHI_PHASE_OUTSIDE;
    uint64_t desired = GEZHI_PHASE_ARMED;

    if (gezhi_load_control() != (LONG64)expected
        || InterlockedCompareExchange(&gezhi_registered, 0, 0) != 0
        || gezhi_load_admission_observer_state() != 0
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
    uint64_t desired = GEZHI_PHASE_ACCEPTING_PRE_ID;
    return (uint64_t)InterlockedCompareExchange64(
        &gezhi_control,
        (LONG64)desired,
        (LONG64)expected) == expected;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_try_answer_id_cutover(void) {
    uint64_t observed;
    uint64_t desired;
    int cutover;

    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return -1;
    }
    if (InterlockedCompareExchange(&gezhi_admission_gate, -1, 0) != 0) {
        return InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0
            ? -1
            : 0;
    }
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return -1;
    }
    observed = (uint64_t)gezhi_load_control();
    if (gezhi_phase(observed) != GEZHI_PHASE_ACCEPTING_PRE_ID
        || (observed & GEZHI_LATCH_BIT) != 0
        || gezhi_generation(observed) != 0) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return 0;
    }
    desired = (observed & ~GEZHI_PHASE_MASK)
        | GEZHI_PHASE_ACCEPTING_POST_ID;
    cutover = (uint64_t)InterlockedCompareExchange64(
        &gezhi_control,
        (LONG64)desired,
        (LONG64)observed) == observed;
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        cutover = -1;
    }
    InterlockedExchange(&gezhi_admission_gate, 0);
    return cutover;
}

__declspec(dllexport) int __stdcall gezhi_cancel_v1_try_begin_work(void) {
    LONG first_gate;
    LONG second_gate;
    uint64_t first_control;
    uint64_t second_control;

    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return -1;
    }
    first_gate = InterlockedCompareExchange(&gezhi_admission_gate, 0, 0);
    first_control = (uint64_t)gezhi_load_control();
    second_control = (uint64_t)gezhi_load_control();
    second_gate = InterlockedCompareExchange(&gezhi_admission_gate, 0, 0);
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return -1;
    }
    if (first_gate != 0 || second_gate != 0 || first_gate != second_gate
        || first_control != second_control) {
        return 0;
    }
    return gezhi_phase_is_accepting(gezhi_phase(first_control))
        && (first_control & GEZHI_LATCH_BIT) == 0;
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
    LONG first_gate;
    LONG second_gate;
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
        first_gate = InterlockedCompareExchange(&gezhi_admission_gate, 0, 0);
        first_in_flight = InterlockedCompareExchange(
            &gezhi_accepted_in_flight, 0, 0);
        ready = InterlockedCompareExchange(&gezhi_publication_ready, 0, 0);
        observation = InterlockedCompareExchange64(&gezhi_observed_ns, 0, 0);
        second_in_flight = InterlockedCompareExchange(
            &gezhi_accepted_in_flight, 0, 0);
        second_gate = InterlockedCompareExchange(&gezhi_admission_gate, 0, 0);
        second_control = (uint64_t)gezhi_load_control();
        if (first_control != second_control
            || first_in_flight != second_in_flight
            || first_gate != second_gate
            || first_gate != 0
            || first_in_flight < 0
            || ready < 0) {
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
    uint64_t observer_state_before_close;
    uint64_t desired;
    int sealed;

    if (candidate_token == 0 || expected_generation > GEZHI_MAX_GENERATION
        || InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return -1;
    }
#ifdef GEZHI_CANCEL_TESTING
    if (InterlockedExchange(&gezhi_test_poison_before_seal_gate, 0) != 0) {
        InterlockedExchange(&gezhi_poisoned, 1);
    }
#endif
    if (InterlockedCompareExchange(&gezhi_admission_gate, -1, 0) != 0) {
        return 0;
    }
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return -1;
    }
#ifdef GEZHI_CANCEL_TESTING
    if (InterlockedCompareExchange(
            &gezhi_test_seal_waiter_race_stage, 2, 1) == 1) {
        while (InterlockedCompareExchange(
                &gezhi_test_seal_waiter_race_stage, 0, 0) < 4) {
            YieldProcessor();
        }
    }
#endif
    observed = (uint64_t)gezhi_load_control();
    if (!gezhi_phase_is_accepting(gezhi_phase(observed))
        || gezhi_generation(observed) != expected_generation) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return 0;
    }
    if ((observed & GEZHI_LATCH_BIT) != 0
        && InterlockedCompareExchange(&gezhi_publication_ready, 0, 0) != 1) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return 0;
    }
#ifdef GEZHI_CANCEL_TESTING
    if (InterlockedExchange(&gezhi_test_poison_before_seal_commit, 0) != 0) {
        InterlockedExchange(&gezhi_poisoned, 1);
    }
#endif
    desired = (observed & ~GEZHI_PHASE_MASK)
        | GEZHI_PHASE_SEALED
        | ((uint64_t)candidate_token << GEZHI_TOKEN_SHIFT);
    sealed = (uint64_t)InterlockedCompareExchange64(
        &gezhi_control,
        (LONG64)desired,
        (LONG64)observed) == observed;
    if (!sealed) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0
            ? -1
            : 0;
    }
    observer_state_before_close = (uint64_t)InterlockedOr64(
        &gezhi_admission_observer_state,
        (LONG64)GEZHI_OBSERVER_CLOSED_BIT);
    if ((observer_state_before_close
            & (GEZHI_OBSERVER_CLOSED_BIT | GEZHI_OBSERVER_FAILED_BIT)) != 0) {
        InterlockedExchange(&gezhi_poisoned, 1);
    }
#ifdef GEZHI_CANCEL_TESTING
    if (InterlockedCompareExchange(
            &gezhi_test_seal_waiter_race_stage, 5, 4) == 4) {
        while (InterlockedCompareExchange(
                &gezhi_test_seal_waiter_race_stage, 0, 0) < 6) {
            YieldProcessor();
        }
    }
#endif
    if (!gezhi_drain_admission_observers()
        || InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        InterlockedExchange(&gezhi_admission_gate, 0);
        return -1;
    }
    InterlockedExchange(&gezhi_admission_gate, 0);
    return 1;
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

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_begin_poison_publication(void) {
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0
        || !gezhi_phase_is_accepting(
            gezhi_phase((uint64_t)gezhi_load_control()))) {
        return 0;
    }
    return InterlockedCompareExchange(&gezhi_admission_gate, 1, 0) == 0;
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_finish_poison_publication(void) {
    if (InterlockedCompareExchange(&gezhi_admission_gate, 1, 1) != 1) {
        return 0;
    }
    InterlockedExchange(&gezhi_poisoned, 1);
    gezhi_leave_admission_gate();
    return 1;
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_poison_before_next_seal_gate(void) {
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return 0;
    }
    return InterlockedCompareExchange(
        &gezhi_test_poison_before_seal_gate, 1, 0) == 0;
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_poison_before_next_seal_commit(void) {
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return 0;
    }
    return InterlockedCompareExchange(
        &gezhi_test_poison_before_seal_commit, 1, 0) == 0;
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_arm_seal_waiter_race(void) {
    if (InterlockedCompareExchange(&gezhi_poisoned, 0, 0) != 0) {
        return 0;
    }
    return InterlockedCompareExchange(
        &gezhi_test_seal_waiter_race_stage, 1, 0) == 0;
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_seal_waiter_race_stage(void) {
    return InterlockedCompareExchange(
        &gezhi_test_seal_waiter_race_stage, 0, 0);
}

__declspec(dllexport) int __stdcall
gezhi_cancel_v1_test_advance_seal_waiter_race(
    uint32_t expected_stage,
    uint32_t next_stage) {
    if (!((expected_stage == 3 && next_stage == 4)
            || (expected_stage == 5 && next_stage == 6))) {
        return 0;
    }
    return InterlockedCompareExchange(
        &gezhi_test_seal_waiter_race_stage,
        (LONG)next_stage,
        (LONG)expected_stage) == (LONG)expected_stage;
}
#endif
