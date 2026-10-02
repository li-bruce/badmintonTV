# CAS之后原生confirm阻塞Edge自动化连接

2026-10-03，平台 A-11 私有18082。状态：浏览器恢复 **BLOCKED**；数据保护断言 **PASS**。

本次实际UI已持有bundle5，将时间轴终点键盘改为67638ms。独立私有API并发保存出bundle6（67637ms）；UI保存返回409并显示“本次草稿未覆盖”，输入67638和dirty状态保留。服务端records/people与冲突前保存对象全等，带两幅ROI的snapshot也成功冻结，证明没有覆盖。

随后点击“放弃当前编辑并重载”，触发原生window.confirm，浏览器工具的点击命令超时。按文档尝试getJsDialog，再重置工具、读取browser-troubleshooting、重新取得同一Edge tab和创建同浏览器新tab，均未恢复。未通过其它技术控制浏览器，也未结束用户进程。已通过用户输入工具请用户关闭该测试弹窗，再继续截图/重载和临时viewport reset。

旧tab ID1438146887；Edge browser2。此前本轮真实save/reload已完成bundle3/4，两幅区域均可回显；不能把之前成功重载替代本次confirm后恢复。问题与服务器CAS拒绝分开记录，未将浏览器自动化恢复标PASS。

证据：`D:/video/platform/training-interaction-20261003/training-interaction-cas.json`、`bundle-before-cas.json`、`concurrent-save.json`、`bundle-after-conflict.json`、`validation-api.json`及本chat工具超时记录。下一步是关闭测试原生弹窗后在同一Edge新tab核验bundle6，并reset1366×768测试视口；若需要产品层优化，可另开明确任务将原生confirm替换为可访问的页面内确认，保留防误丢稿语义。

收尾回执：root已在独立18084完成实际保存/重载和最终集成截图，并要求本模块停止恢复尝试、提交事实报告。本轮不再要求用户为验收关闭弹窗。旧tab恢复及viewport reset仍未验证，不能因独立实例通过而把它们改写为PASS；产品整项由root的独立证据补齐。
