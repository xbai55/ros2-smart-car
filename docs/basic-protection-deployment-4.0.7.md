# 基础防护 4.0.7 部署记录

已按用户后续部署指令更新电脑客户端和小车。部署前通过独立停止接口释放控制权，并确认底盘静止。没有申请运动租约，没有发送驾驶指令或开展行驶验收。

## 已生效内容

- Windows 客户端已覆盖安装为 4.0.7，程序及内置界面文件与本次构建一致，账号、连接配置及凭据沿用原配置。
- 车端运行目录：`/home/jetson/insightrover-v407-basic-protection-821203fc5486`，服务为 `smart-car-v4.service`。
- 当前防护模式为 `basic`，主动绕行 `enabled=false`。原绕行触发距离 0.4 米保留，不修改车体尺寸或自体过滤范围。
- 旧车端目录 `/home/jetson/insightrover-v406-vehicle-size-facde8625d12`完整保留，未覆盖原安装。

打开客户端，在“设置 → 运动防护”中可开启完整防护。主动绕行仍是独立开关。配置只在停止、确认静止并释放控制权后应用，以控制器回执为准。

## 部署后验证

已验证实际安装程序返回版本 4.0.7，能够读取真实车端状态、通过鉴权的状态 WebSocket，以及完成基础防护设置请求和匹配回执。车端上传资源及 62 个 Python 源文件的哈希与本地一致，传感器就绪。

最终状态为停止模式、控制权无人持有、平面速度为零。只读订阅连续记录了 61 条零速度输出，`/cmd_vel`唯一发布者为 `decision_controller`。

安装包经过资源、图标及无用户数据混入检查：`output/windows-v407-basic-protection/installer/InsightRover-Setup-4.0.7-x64.exe`。

部署、安装和核查证据位于 `output/safety-basic-deployment/`：`deployment-summary.json`、`vehicle-verification.json`、`installed-verification.json`、`windows-installation.json`。软件构建证据在安装包目录的 `software-build-verification.json`。

这些结果证明部署和静止链路正常，不证明实际制动距离、行驶避障或右侧近车体回波来源已通过实车验收。

## 回退保留

车端新目录保存 `previous.service`及原避障设置备份；电脑旧程序备份在 `output/safety-basic-deployment/windows-before-4.0.7/`，升级前数据库另有本地备份。现有系统服务自启动策略没有修改。

回退前必须通过正常停止入口停车并确认静止、释放控制权。车端可使用本次部署辅助脚本的 `rollback`操作恢复原服务及避障设置，电脑端对应恢复 4.0.6；两端协议须配套，不能在行驶中切换版本。回退不能恢复旧的运行任务或按住状态。
