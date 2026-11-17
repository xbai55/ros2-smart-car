# 业务任务与车端记录一致性修复（4.1.1）

本轮仅本地修改与离线验证，未部署、未连接或控制实车，未修改实际业务数据库。此前终点容差修复等工作区改动保持原样。

## 证据与根因

此前只读检查确认：patrol_tasks 中业务任务 f5660430-5282-5ce4-96da-5494bc969bc4 保存了 run_id=f81adb16-28d6-4baa-bfcf-a341732b05ae、state=unconfirmed 及原请求；车端 GET /api/navigation/task?run_id=... 返回 422，原因为车端没有此执行记录。客户端每秒对账并重复报错。

确认的问题：snapshot_for 将无记录作为普通 ValueError；task_reconciler 吞掉异常、无退避或收敛；业务 GET 也没有分类；前端 POST 失败后仅保留 run_id，重新读取当前编辑内容构造请求，容易与原指纹冲突；当前车端 idle 的轮询还可能遮住本地未确认请求。车端已有取消 tombstone，但无指纹的 tombstone 导致迟到创建被报告为内容冲突，而不是明确取消。

## 协议与状态

车端无记录返回 404，detail.code=NAVIGATION_RUN_NOT_FOUND。保留旧车端确切 422 文案兼容，不能把所有 404/422 都归为无记录。

不新增数据库表或更换任务生命周期，用执行记录中的 sync_state、poll_required、next_poll_at 和 sync_failures 表达同步状态：
- confirmed：匹配的车端记录，保留车端 prepared/running/completed/cancelled/failed 等阶段。
- record_missing：明确无记录，保持原 unconfirmed，不猜测已停止；暂停自动车端轮询，等待明确的重试或取消。
- unreachable：无法连接/请求超时，仍不确定是否执行；2、4、8、16、30 秒退避，不自动重新派发。
- record_mismatch：run_id/task_id/kind/状态不匹配，暂停自动查询，禁止重试派发。
- query_rejected/dispatch_rejected：其他协议、响应或请求问题，明确显示原因并停止无意义查询。
- cancel_pending：已要求取消但未获确认，持久化屏障，阻止原请求重试及迟到非终态覆盖；允许再次取消核对。

业务 API 在创建已持久化、车端回执丢失时返回 HTTP 200 的 unconfirmed 执行记录（包含任务标识和同步状态），不表示已派发成功或已开始行驶。无权限/请求内容冲突等仍返回明确错误。

## 幂等与取消

保存的 request 与 request_fingerprint 在车端状态更新时始终保留，不接受响应覆盖。重试只从服务器保存的请求读取，先查询车端：已有匹配记录就接纳，不再 POST；明确无记录且原阶段为 unconfirmed 才用完全相同 run_id、task_id、指纹和请求内容提交；失联或不匹配不盲目重发。重复创建的请求内容仍必须匹配保存指纹。

取消前保存 cancel_pending。只有车端取消确认后界面才允许走重新创建流程；新任务使用新 run_id 与新业务任务，不复用旧 task_id。取消回执丢失时仍保持屏障，不伪造取消成功。车端将未派发请求的取消持久化为 tombstone；迟到同身份 create 返回 cancelled，不执行、不再显示普通指纹错误；重启后仍有效。历史记录取消校验业务身份，不影响当前另一个任务。终态不能被迟到的更高版本非终态覆盖，数据库仍使用 CAS。绑定变化期间的旧响应丢弃。

前端继续提供“核对并重试原请求”，新增“取消旧任务并重新创建”：先等待取消确认，再解锁新任务编辑，不自动启动任务。选择已有业务任务时读取其保存执行状态；不让车端 idle 覆盖本地未确认/终态记录。旧轮询按发起时 run_id 防止覆盖新创建任务。

## 文件

backend/app/api/routes/navigation_tasks.py；services/navigation_execution.py、task_reconciler.py、task_sync.py（新增）。
车端 navigation_tasks.py、web_api.py。
前端 NavigationOperations.tsx、TaskExecutionControls.tsx、navigationTaskState.ts、robotApi.ts。
测试 backend/tests/test_navigation_execution.py、tests/test_navigation_tasks.py、web-console/tests/navigationTaskState.test.ts。

## 验证与边界

后端全量 278 项通过；车端全量 576 项及 5 个子测试通过，继续排除既有两项 test_failed_slam_restart_cannot_restore_old_registration、test_temporary_disk_error_retries_the_same_event_and_picture；前端 130 项通过，构建及最终 TypeScript 检查通过。仅有既有依赖弃用及打包体积警告。

专项覆盖创建响应丢失、明确无记录后的查询暂停、网络退避、原指纹及请求保持、修改内容拒绝、记录不匹配禁止派发、取消响应丢失后屏障、另一客户端取消后迟到高版本响应、并发取消与创建、tombstone 重启保持、错误业务身份不能取消当前任务、idle 及旧轮询不能复活旧状态。

未执行浏览器交互或实车验收。当前线上旧记录并未被本轮修改；部署后第一次查询会分类并收敛，用户须通过原请求重试或确认取消旧请求后重新创建，不自动清理数据库或重新派发。未改导航启动、控制租约、防撞、急停或真实运动逻辑。


## 后续授权部署与静止验证

用户随后授权处理旧任务并部署。车端新目录 insightrover-v411-task-consistency-37926128f27a，电脑客户端同步更新，版本仍为 4.1.1；旧程序和实际业务数据库已备份。网络恢复后发现车端 InsightRover 服务未运行、原厂 rosmaster_main 占用底盘；核实 KeyboardInterrupt 会发送零速后，正常退出该精确进程，再启动 InsightRover 并确认静止，未绕过占用检查。

联合运行 backend/tests 与 tests 时发现测试中的 conftest 同名导入冲突，已改为使用 TestClient 的数据库依赖覆盖获取隔离会话，生产代码不变；31 项联合专项回归通过。

通过实际安装的客户端后台核对指定旧巡航：无记录分类为 record_missing、poll_required=false；通过业务 API 取消后，业务状态及车端 tombstone 均为 cancelled。两次重复取消保持终态；向 Jetson 重放同一已取消 run_id 的原创建请求仍返回 cancelled，不创建或执行任务。最终 task runner=idle、mode=stop、速度为零、控制权无人持有。没有发 start/resume、导航目标或速度指令。

车端重启未恢复旧任务、租约或定位，后续新建任务前需重新加载地图并定位。实际验证、程序哈希与配置备份在 output/task-consistency-deploy/，原始数据库与日志不纳入源代码提交。
