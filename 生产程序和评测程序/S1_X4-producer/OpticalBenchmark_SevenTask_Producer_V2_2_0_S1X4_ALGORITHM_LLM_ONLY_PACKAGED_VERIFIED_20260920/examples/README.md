# Schema测试样例

- `valid/`：每类根对象至少一个合法正例，并包含Request JSONL正例。
- `invalid/<object>/`：缺失必填字段、类型错误、越界、禁止旧字段，以及存在枚举或固定候选值时的枚举/受控值错误。
- `test_suite.json`：记录Schema、样例路径和预期有效性。
- `test_coverage.csv`：记录各对象的测试类别覆盖；冻结对象没有枚举或`const`字段时，枚举错误标记为不适用，不人为新增字段。

动态请求序列额外覆盖：

- `release_time`；
- `initial_resource_state_id`；
- `initial_existing_connection_set_id`；
- `holding_time <= 0`；
- `required_slots = 4`；
- `arrival_rate_lambda <= 0`。
