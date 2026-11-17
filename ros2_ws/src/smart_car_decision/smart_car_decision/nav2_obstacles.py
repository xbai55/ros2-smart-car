"""Apply the single avoidance setting to Nav2 before a stationary preview."""
import asyncio
import time


class Nav2Obstacles:
    def __init__(self, node):
        self.node = node
        self.applied = None
        self.message = '等待路线预览确认 Nav2 配置'
        self.lock = asyncio.Lock()

    def snapshot(self):
        return {'enabled': self.applied, 'message': self.message}

    async def apply(self, enabled, wait):
        async with self.lock:
            if self.applied is enabled:
                return
            self.applied = None
            self.message = '正在确认 Nav2 动态障碍层'
            from rcl_interfaces.srv import SetParameters
            from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType
            from nav2_msgs.srv import ClearEntireCostmap
            try:
                for scope in ('local', 'global'):
                    parameter = Parameter(name='obstacle_layer.enabled', value=ParameterValue(
                        type=ParameterType.PARAMETER_BOOL, bool_value=enabled))
                    await self._call(SetParameters, f'/{scope}_costmap/{scope}_costmap/set_parameters',
                                     SetParameters.Request(parameters=[parameter]), wait, parameters=True)
                    # Discard old marked obstacles after changing a layer. The
                    # static layer and measured footprint remain unchanged.
                    await self._call(ClearEntireCostmap, f'/{scope}_costmap/clear_entirely_{scope}_costmap',
                                     ClearEntireCostmap.Request(), wait)
            except Exception:
                self.message = 'Nav2 避障配置未确认，禁止启动，请重新预览'
                raise
            self.applied = enabled
            self.message = 'Nav2 雷达动态绕行已启用' if enabled else 'Nav2 静态地图导航，雷达近障停车保留'

    async def _call(self, service, name, request, wait, parameters=False):
        client = self.node.create_client(service, name)
        try:
            deadline = time.monotonic() + 2.
            while not client.service_is_ready():
                if time.monotonic() >= deadline:
                    raise RuntimeError('Nav2 配置服务未就绪：' + name)
                await asyncio.sleep(.05)
            result = await wait(client.call_async(request))
            if parameters and (len(result.results) != 1 or not result.results[0].successful):
                raise RuntimeError('Nav2 拒绝动态障碍配置：' + name)
        finally:
            self.node.destroy_client(client)
