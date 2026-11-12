"""Export the same editable monochrome layout to SVG and uncompressed Draw.io.

Run from any directory: python docs/architecture/build_architecture.py
PNG export uses render_architecture.cjs with the bundled sharp package.
"""
from pathlib import Path
from html import escape
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
W, H = 2560, 1440
nodes, edges, notes = [], [], []


def box(key, x, y, w, h, title, lines=(), size=25, group=False, dashed=False):
    nodes.append(dict(id=key, x=x, y=y, w=w, h=h, title=title,
                      lines=list(lines), size=size, group=group, dashed=dashed))


def link(key, source, target, points, label='', at=None, dashed=False, control=False, both=False):
    edges.append(dict(id=key, source=source, target=target, points=points, label=label,
                      at=at, dashed=dashed, control=control, both=both))


def note(x, y, value, size=21, anchor='middle'):
    notes.append(dict(x=x, y=y, text=value, size=size, anchor=anchor))


# Deployment regions and logical groups. All dimensions use a 16:9 canvas.
box('host', 30, 115, 905, 1255, '主机端｜业务管理与智能编排', group=True)
box('car', 1060, 115, 1470, 1060, 'Jetson 车端｜ROS 2 Humble 感知、导航与控制', group=True)
box('hardware', 1060, 1210, 1470, 160, '机器人硬件', group=True)
box('execution', 65, 805, 640, 225, '持久任务执行与状态管理', group=True, dashed=True)
box('vision', 1100, 480, 350, 480, '视觉感知', group=True, dashed=True)
box('navigation', 1490, 480, 400, 480, '自主导航', group=True, dashed=True)
box('control', 1925, 480, 575, 660, '运动控制与安全', group=True, dashed=True)

box('desktop', 65, 185, 205, 115, 'Windows', ['桌面入口', '启动本机服务'], 24)
box('ui', 315, 185, 390, 115, 'React 管理控制台', ['悬浮 Agent 助手 / 任务卡片'], 27)
box('api', 65, 375, 640, 105, 'FastAPI 业务接口层', ['身份认证 · JWT · RBAC 权限管理'], 28)
box('agent', 65, 535, 300, 215, 'Agent 智能编排',
    ['提供器 ↔ 外部大模型 API', '意图理解 · 工具注册与调用', '计划组织 · 业务能力调用'], 26)
box('business', 405, 535, 300, 215, '核心业务服务',
    ['地图路线 · 巡检 · 文件运输', '异常事件 · 机器人状态', '普通业务任务入口'], 26)
box('worker', 85, 865, 180, 140, '助手计划推进', ['AssistantWorker', '多步骤 / 人工交接'], 22)
box('shared', 285, 865, 195, 140, '共享业务执行', ['导航 / 巡检 / 运输', '搜索 / 短距动作'], 23)
box('reconcile', 500, 865, 185, 140, '执行状态管理', ['任务对账 / 进度', '结果持久记录'], 23)
box('ingest', 65, 1085, 640, 90, '反馈同步与异常证据接收',
    ['遥测快照 · 任务回执 · 诊断日志 · 事件与图片'], 26)
box('store', 65, 1250, 640, 90, '数据存储', ['业务数据库 · 会话 / 执行记录 · 媒体与异常证据'], 26)
box('gateway', 755, 535, 170, 485, '主机通信适配',
    ['RobotGateway', 'HTTP 调用', '任务 / 导航目标', '模式 / 控制意图', '状态 / 日志', '异常证据', '', '状态 WS 代理', 'vehicle_control', '', '机器鉴权 / 租约'], 22)

box('web', 1100, 185, 350, 140, 'ROS 2 车端 Web 服务',
    ['web_app_node / Web API', '鉴权 · 租约请求与回执'], 26)
box('task', 1510, 185, 360, 140, '车端导航任务管理',
    ['NavigationTaskRunner', 'NavigationBridge · ROS 2 Action'], 25)
box('mode', 1945, 185, 530, 140, '模式管理与控制意图接入',
    ['mode_manager · 手动 / 模式 / 急停', '控制租约请求与回执'], 26)
box('status', 1100, 370, 350, 65, '状态汇总与诊断反馈', [], 25)
box('camera', 1120, 535, 310, 70, '共享相机服务', ['CameraStream / 原始帧'], 25)
box('models', 1120, 650, 310, 150, '通用与专项视觉模型',
    ['YOLOE 通用目标检测', '人员倒地专项 · 烟火专项'], 25)
box('events', 1120, 855, 310, 75, '异常候选与事件确认', ['图片 / 事件落盘 · 证据回传'], 23)
box('slam', 1510, 535, 360, 70, 'SLAM Toolbox 建图', [], 25)
box('map', 1510, 655, 165, 75, '地图资产', ['栅格保存 / 加载'], 23)
box('amcl', 1710, 655, 160, 75, 'AMCL 定位', ['map → odom'], 22)
box('nav2', 1510, 845, 360, 85, 'Nav2 路径规划与导航控制', ['规划器 · 控制器 · 速度平滑'], 24)
box('manual', 1945, 535, 250, 80, '手动与其他模式意图', ['/manual_cmd 等'], 23)
box('search', 2225, 655, 250, 80, '搜索控制意图', ['VisionService → 停车锁'], 23)
box('navspeed', 1945, 655, 250, 80, '自动导航速度', ['/navigation/cmd_vel'], 24)
box('controller', 1945, 845, 530, 130, 'decision_controller',
    ['统一控制与安全仲裁', '雷达安全检测 · 急停 · 超时 · 控制租约'], 30)
box('driver', 1945, 1055, 530, 65, 'Yahboom 底盘软件驱动', [], 26)
box('inputs', 1490, 1025, 400, 115, 'ROS 2 传感与坐标信息',
    ['/scan · /odom · TF', '雷达驱动 / 里程计 / IMU 滤波 / EKF'], 24)
box('jetson', 1100, 1265, 260, 80, 'Jetson Orin Nano', ['承载上方车端软件'], 24)
box('camhw', 1385, 1265, 220, 80, '相机', ['USB 图像采集'], 25)
box('lidarhw', 1630, 1265, 220, 80, '激光雷达', ['激光扫描数据'], 25)
box('feedbackhw', 1875, 1265, 270, 80, '底盘反馈硬件', ['编码器 / IMU'], 25)
box('motor', 2170, 1265, 305, 80, 'Yahboom X3 底盘', ['四轮电机执行'], 25)

# Host business, orchestration, persistence and independent feedback paths.
link('desktop-ui', 'desktop', 'ui', [(270,242),(315,242)])
link('ui-api', 'ui', 'api', [(665,300),(665,375)], both=True)
link('api-agent', 'api', 'agent', [(215,480),(215,535)])
link('api-business', 'api', 'business', [(555,480),(555,535)])
link('agent-business', 'agent', 'business', [(365,642),(405,642)])
link('agent-worker', 'agent', 'worker', [(175,750),(175,865)], '确认计划', (174,783))
link('business-shared', 'business', 'shared', [(555,750),(555,775),(382,775),(382,865)])
link('worker-shared', 'worker', 'shared', [(265,935),(285,935)])
link('shared-reconcile', 'shared', 'reconcile', [(480,935),(500,935)], dashed=True)
link('shared-gateway', 'shared', 'gateway', [(382,1005),(382,1055),(730,1055),(730,935),(755,935)], control=True)
link('business-gateway', 'business', 'gateway', [(705,600),(755,600)])
link('gateway-ingest', 'gateway', 'ingest', [(755,985),(740,985),(740,1130),(705,1130)], dashed=True)
link('ingest-reconcile', 'ingest', 'reconcile', [(592,1085),(592,1005)], dashed=True)
link('ingest-store', 'ingest', 'store', [(385,1175),(385,1250)])
link('execution-store', 'execution', 'store', [(65,945),(48,945),(48,1295),(65,1295)])
link('ingest-api', 'ingest', 'api', [(65,1125),(42,1125),(42,425),(65,425)], dashed=True)
link('api-gateway', 'api', 'gateway', [(705,425),(735,425),(735,550),(755,550)])

# Only the narrow band is a network boundary; adapters stay inside the host.
link('http', 'gateway', 'web', [(925,620),(980,620),(980,225),(1100,225)], both=True)
link('ws', 'web', 'gateway', [(1100,285),(1020,285),(1020,760),(925,760)], dashed=True)
note(974,470,'HTTP',22)
note(1018,825,'WS',22)
note(997,925,'局域网',23)
note(997,960,'通信边界',23)

# Car Web API owns task and service objects; arrows do not imply extra servers.
link('web-task', 'web', 'task', [(1450,255),(1510,255)], '任务/回执', (1480,230), both=True)
link('web-mode', 'web', 'mode', [(1320,185),(1320,157),(2210,157),(2210,185)])
link('status-web', 'status', 'web', [(1275,370),(1275,325)], dashed=True)
link('web-camera', 'web', 'camera', [(1100,300),(1082,300),(1082,570),(1120,570)])
link('camera-models', 'camera', 'models', [(1275,605),(1275,650)])
link('models-events', 'models', 'events', [(1275,800),(1275,855)])
link('events-status', 'events', 'status', [(1430,892),(1468,892),(1468,402),(1450,402)], dashed=True)
link('task-nav2', 'task', 'nav2', [(1690,325),(1690,390),(1498,390),(1498,887),(1510,887)], '导航目标 / Action', (1660,425), control=True)
link('mode-manual', 'mode', 'manual', [(1945,285),(1933,285),(1933,575),(1945,575)], control=True)
link('web-search', 'web', 'search', [(1450,300),(1480,300),(1480,450),(2495,450),(2495,695),(2475,695)], control=True)
link('manual-control', 'manual', 'controller', [(2070,615),(2208,615),(2208,800),(2210,800),(2210,845)], control=True)
link('search-control', 'search', 'controller', [(2350,735),(2350,845)], control=True)
link('nav2-speed', 'nav2', 'navspeed', [(1870,890),(1910,890),(1910,695),(1945,695)], control=True)
link('speed-control', 'navspeed', 'controller', [(2070,735),(2070,845)], control=True)
link('control-driver', 'controller', 'driver', [(2210,975),(2210,1055)], '/cmd_vel', (2210,1019), control=True)
link('control-status', 'controller', 'status', [(2475,900),(2520,900),(2520,350),(1475,350),(1475,402),(1450,402)], dashed=True)
note(2180,395,'运行状态 / 控制回执',21)

# SLAM produces a map asset; localization and navigation consume it separately.
link('slam-map', 'slam', 'map', [(1592,605),(1592,655)], '保存', (1592,635))
link('map-amcl', 'map', 'amcl', [(1675,692),(1710,692)])
link('map-nav2', 'map', 'nav2', [(1592,730),(1592,845)], '地图', (1592,790))
link('amcl-nav2', 'amcl', 'nav2', [(1790,730),(1790,845)], '位姿 / TF', (1790,790))
link('sensor-status', 'inputs', 'status', [(1490,1115),(1460,1115),(1460,420),(1450,420)], dashed=True)
link('sensor-nav', 'inputs', 'navigation', [(1540,1025),(1540,960)])
link('sensor-control', 'inputs', 'controller', [(1890,1080),(1900,1080),(1900,945),(1945,945)], control=True)

link('cam-svc', 'camhw', 'camera', [(1495,1265),(1495,1190),(1074,1190),(1074,570),(1120,570)])
link('lidar-input', 'lidarhw', 'inputs', [(1740,1265),(1740,1140)])
link('feedback-input', 'feedbackhw', 'inputs', [(2010,1265),(2010,1190),(1830,1190),(1830,1140)], dashed=True)
link('driver-motor', 'driver', 'motor', [(2310,1120),(2310,1265)], control=True)
note(2380,1202,'底盘串口控制',21)
note(1740,1206,'/scan',21)
note(2010,1225,'编码器 / IMU 数据',20)

note(1280,58,'智巡 InsightRover 系统总体架构',42)
note(1280,96,'用户请求 → 业务编排 → 任务下发 → 现场感知与导航 → 安全执行 → 状态与证据反馈',25)
note(325,334,'HTTP：业务请求　WS：状态',20)
note(325,360,'SSE：助手回复与执行事件',20)
note(833,1060,'同一主机进程内',20)

note(1280,1415,'实线箭头：业务调用 / 数据输入　　粗实线：运动控制意图与执行　　虚线：状态 / 回执 / 证据反馈',22)


def text_svg(x, y, text, size=24, bold=False, anchor='middle'):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
            f'font-size="{size}" font-weight="{700 if bold else 400}">{escape(text)}</text>')


def build_svg():
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
        '<title id="title">智巡 InsightRover 系统总体架构</title>',
        '<desc id="desc">黑白横向部署架构。主机业务、Agent 编排与持久任务执行通过主机内部车辆通信适配连接 Jetson Web 服务；视觉、建图、定位、Nav2 及控制意图汇入统一安全控制器，最终经底盘驱动执行并反馈。</desc>',
        '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0 0 L9 4.5 L0 9 Z" fill="#000"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<g font-family="Microsoft YaHei,SimHei,Arial,sans-serif" fill="#000">']
    for n in nodes:
        if n['group']:
            dash = ' stroke-dasharray="9 6"' if n['dashed'] else ''
            parts.append(f'<rect id="{n["id"]}" x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="0" fill="#fff" stroke="#000" stroke-width="1.8"{dash}/>')
            parts.append(text_svg(n['x']+18,n['y']+36,n['title'],27,True,'start'))
    for e in edges:
        pts = ' '.join(f'{x},{y}' for x,y in e['points'])
        width = 3 if e['control'] else 1.8
        dash = ' stroke-dasharray="8 6"' if e['dashed'] else ''
        start = ' marker-start="url(#arrow)"' if e['both'] else ''
        parts.append(f'<polyline id="{e["id"]}" points="{pts}" fill="none" stroke="#000" stroke-width="{width}" marker-end="url(#arrow)"{start}{dash}/>')
    for n in nodes:
        if n['group']:
            continue
        parts.append(f'<g id="{n["id"]}"><rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" fill="#fff" stroke="#000" stroke-width="1.8"/>')
        rows = [n['title'], *n['lines']]
        step = 32 if len(rows)<5 else 34
        total = (len(rows)-1)*step
        baseline = n['y'] + (n['h']-total)/2 + n['size']*.35
        for i, row in enumerate(rows):
            parts.append(text_svg(n['x']+n['w']/2,baseline+i*step,row,n['size'] if i==0 else min(n['size']-2,22),i==0))
        parts.append('</g>')
    for e in edges:
        if e['label']:
            x,y=e['at']
            # White backing keeps an edge label readable without changing style.
            width = len(e['label'])*13+12
            parts.append(f'<rect x="{x-width/2}" y="{y-22}" width="{width}" height="28" fill="#fff"/>')
            parts.append(text_svg(x,y,e['label'],21))
    for n in notes:
        parts.append(text_svg(n['x'],n['y'],n['text'],n['size'],n['size']>=27,n['anchor']))
    parts.append('</g></svg>')
    (ROOT/'insightrover-system-architecture.svg').write_text('\n'.join(parts),encoding='utf-8')


def build_drawio():
    mxfile=ET.Element('mxfile',host='app.diagrams.net',version='24.7.17')
    diagram=ET.SubElement(mxfile,'diagram',id='insightrover-overview',name='系统总体架构')
    model=ET.SubElement(diagram,'mxGraphModel',dx=str(W),dy=str(H),grid='1',gridSize='10',page='1',pageWidth=str(W),pageHeight=str(H),math='0',shadow='0')
    root=ET.SubElement(model,'root'); ET.SubElement(root,'mxCell',id='0'); ET.SubElement(root,'mxCell',id='1',parent='0')
    # Explicit points preserve the reviewed SVG layout in the editable source.
    for n in nodes:
        value='<b>'+escape(n['title'])+'</b>'
        if n['lines']:
            value+=f'<div style="font-size:{min(n["size"]-2,22)}px;line-height:1.45">'+ '<br>'.join(escape(t) or '&nbsp;' for t in n['lines'])+'</div>'
        style=f'rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;strokeWidth=1.8;fontColor=#000000;fontFamily=Microsoft YaHei;fontSize={n["size"]};'
        if n['group']:
            style+='verticalAlign=top;align=left;spacingLeft=18;spacingTop=12;fontStyle=1;'
        else:
            style+='align=center;verticalAlign=middle;'
        if n['dashed']: style+='dashed=1;dashPattern=9 6;'
        cell=ET.SubElement(root,'mxCell',id=n['id'],value=value,style=style,vertex='1',parent='1')
        ET.SubElement(cell,'mxGeometry',x=str(n['x']),y=str(n['y']),width=str(n['w']),height=str(n['h']),attrib={'as':'geometry'})
    for e in edges:
        style='endArrow=block;endFill=1;html=0;rounded=0;strokeColor=#000000;fontColor=#000000;fontSize=21;'
        style+=f'strokeWidth={3 if e["control"] else 1.8};'
        if e['dashed']:style+='dashed=1;dashPattern=8 6;'
        if e['both']:style+='startArrow=block;startFill=1;'
        by_id={n['id']:n for n in nodes}
        sn,tn=by_id[e['source']],by_id[e['target']]
        x,y=e['points'][0];tx,ty=e['points'][-1]
        style+=f'exitX={(x-sn["x"])/sn["w"]};exitY={(y-sn["y"])/sn["h"]};exitPerimeter=0;entryX={(tx-tn["x"])/tn["w"]};entryY={(ty-tn["y"])/tn["h"]};entryPerimeter=0;'
        cell=ET.SubElement(root,'mxCell',id=e['id'],style=style,edge='1',parent='1',source=e['source'],target=e['target'])
        geom=ET.SubElement(cell,'mxGeometry',relative='1',attrib={'as':'geometry'})
        for tag,p in [('sourcePoint',e['points'][0]),('targetPoint',e['points'][-1])]:
            ET.SubElement(geom,'mxPoint',x=str(p[0]),y=str(p[1]),attrib={'as':tag})
        points=ET.SubElement(geom,'Array',attrib={'as':'points'})
        for x,y in e['points'][1:-1]: ET.SubElement(points,'mxPoint',x=str(x),y=str(y))
    for i,n in enumerate(notes+[{**dict(x=e['at'][0],y=e['at'][1],text=e['label'],size=21,anchor='middle')} for e in edges if e['label']]):
        width=max(160,len(n['text'])*n['size'])
        style=f'text;html=0;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontColor=#000000;fontFamily=Microsoft YaHei;fontSize={n["size"]};'
        c=ET.SubElement(root,'mxCell',id=f'note-{i}',value=n['text'],style=style,vertex='1',parent='1')
        ET.SubElement(c,'mxGeometry',x=str(n['x']-width/2),y=str(n['y']-n['size']),width=str(width),height=str(n['size']+8),attrib={'as':'geometry'})
    ET.indent(mxfile)
    ET.ElementTree(mxfile).write(ROOT/'insightrover-system-architecture.drawio',encoding='utf-8',xml_declaration=True)


def build_mermaid():
    lines=['%% Current-code overview; precise report/PPT layout is in architecture/*.drawio and *.svg.',
           '%% This replaces the previous assistant-centric TB diagram without changing runtime architecture.',
           '%%{init: {"theme":"base","themeVariables":{"primaryColor":"#ffffff","primaryTextColor":"#000000","primaryBorderColor":"#000000","lineColor":"#000000","clusterBkg":"#ffffff","clusterBorder":"#000000","fontFamily":"Microsoft YaHei, Arial, sans-serif"},"flowchart":{"curve":"linear","htmlLabels":true}}}%%',
           'flowchart LR']
    def node(n):
        value='<br/>'.join([n['title'],*n['lines']]).replace('"', '&quot;')
        lines.append(f'    {n["id"]}["{value}"]')
    def cluster(key,title,children):
        lines.extend([f'  subgraph {key}["{title}"]','    direction TB'])
        for ident in children:
            n=next(n for n in nodes if n['id']==ident)
            node(n)
        lines.append('  end')
    lines.extend(['  subgraph host["主机端：业务管理与智能编排"]','    direction TB'])
    for ident in ['desktop','ui','api','agent','business']:
        node(next(n for n in nodes if n['id']==ident))
    cluster('execution','持久任务执行与状态管理',['worker','shared','reconcile'])
    for ident in ['gateway','ingest','store']:node(next(n for n in nodes if n['id']==ident))
    lines.append('  end')
    lines.extend(['  subgraph car["Jetson 车端：ROS 2 Humble 感知、导航与控制"]','    direction TB'])
    for ident in ['web','task','mode','status']:node(next(n for n in nodes if n['id']==ident))
    cluster('vision','视觉感知',['camera','models','events'])
    cluster('navigation','自主导航',['slam','map','amcl','nav2'])
    cluster('control','运动控制与安全',['manual','search','navspeed','controller','driver'])
    node(next(n for n in nodes if n['id']=='inputs'))
    lines.append('  end')
    cluster('hardware','机器人硬件',['jetson','camhw','lidarhw','feedbackhw','motor'])
    for e in edges:
        op='<-->' if e['both'] else '-.->' if e['dashed'] else '==>' if e['control'] else '-->'
        label=e['label']
        if e['id']=='http':label='HTTP：任务 / 目标 / 设置 / 查询与证据'
        if e['id']=='ws':label='WebSocket：车端状态代理'
        if e['id']=='ui-api':label='HTTP / WebSocket / SSE'
        lines.append(f'  {e["source"]} {op}'+(f'|"{label}"|' if label else '')+f' {e["target"]}')
    lines.extend(['  classDef default fill:white,stroke:black,color:black,stroke-width:1px;',
                  '  linkStyle default stroke:black,color:black;'])
    (ROOT.parent/'patrol-assistant-architecture.mmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    build_svg(); build_drawio(); build_mermaid()
    (ROOT/'architecture-layout.json').write_text(json.dumps(dict(width=W,height=H,nodes=nodes,edges=edges,notes=notes),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Exported {len(nodes)} nodes and {len(edges)} connections.')
