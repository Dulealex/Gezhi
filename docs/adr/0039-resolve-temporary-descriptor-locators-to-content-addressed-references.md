# 将临时 Descriptor Locator 解析为内容寻址引用

Codex 输出中的 `DescriptorLocatorV1` 只使用 kind 与 Reading Result 数组的 0-based index 临时定位 Method 或 Study Descriptor，从而避免复制描述符内容或要求模型生成稳定 ID。Python 在发布前验证定位，把证据转换为内容寻址 Evidence Pointer，并按 `gezhi.descriptor_payload.v1` 的 kind 与完整规范化 value 计算 SHA-256；`descriptor_id` 为 `desc_<前24位>`，正式 `DescriptorReferenceV1` 保存 Schema 版本、kind、短 ID 与完整 payload hash。数组位置不进入持久 Candidate 身份，相同内容确定性归并；未知类型、越界、无法解析或任一短 ID/完整 hash 碰撞使整个 semantic run 失败且不部分发布，具体哈希前像与排序以 [Candidate Knowledge v1 合同](../contracts/candidate-knowledge-v1.md) 为准。
