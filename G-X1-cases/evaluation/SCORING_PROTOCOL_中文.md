# GX1冻结评分口径

科学核：V5 R1的 gx1/validators.py 和 common.py 原字节保留，SHA256绑定，同当前本机Inspect科学代码。公共长度按六位有效数字计算。源root/truth/reference完整保留；evaluation_reference_output仅重算加权题总长度声明，路径/决定不变。G3_000260保留REVIEW并默认不派发。

G1/G2/G3报告正确与不正确，错误原因继续保留。G1图表示规范化后检查图是否等价；G2检查路径合法性标签及错误类型；G3检查两条最短路、链路方向及共享关系。

X1为图上的最短路径，HOP_COUNT或TOTAL_LENGTH_KM由题目指定。四类为CORRECT（最优）、SUBOPTIMAL（合法但更长）、INFEASIBLE（路径或成本声明不合法）、MISSING（无可解析合规输出）。本批X1均有解，没有REJECT字段。该分类与当前本机GX1 Inspect适配口径一致，不修改科学Validator。有效但优于真值的路径进入REVIEW_ORACLE。

仅移除整个回答最外层一层代码围栏，并同时记录原样严格评分；其余内容不修复、不挑选。服务错误、REVIEW、评分异常单独计数。正确率分母是已完成评分的回答，同时报告计划数量、完成数量与失败服务请求。公开消息与源消息绑定；私有truth、root、reference不作为模型输入。

Inspect负责调用、答卷记录、日志；冻结Validator负责科学判断。日志包含最终回答及平台usage，不主动导出原始隐含思维；框架日志的公开前需按平台实际字段复核。不同模型必须使用同一冻结选样和题面。条件比较需固定配置与样本，不根据结果筛选有利样本。
