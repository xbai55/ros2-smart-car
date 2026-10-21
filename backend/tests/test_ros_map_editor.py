import base64
import copy
import io
import json
import zipfile
from uuid import uuid4

import pytest

from app.services.map_optimization import optimize_snapshot, isolated_candidates
from app.services.ros_map_io import import_snapshot, pgm_pixels
from app.services.slam_maps import snapshot_assets


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path,monkeypatch):
    from app.services import storage
    monkeypatch.setattr(storage,'_storage',storage.LocalStorageService(str(tmp_path/'storage')))


def grid():
    return {'session_id':'editor-test','header':{'frame_id':'map'},'info':{'width':20,'height':20,'resolution':.05,'origin':{'x':-1,'y':2,'yaw':.3}},'data':[0]*400}


def pair(pgm=b'P5\n2 2\n255\n'+bytes([0,254,205,254]),name='map.pgm'):
    return {'filename':name,'pgm_base64':base64.b64encode(pgm).decode(),'yaml':f'image: {name}\nresolution: 0.05\norigin: [-1, 2, 0.3]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n'}


@pytest.mark.parametrize('shape,filled', [('brush',False),('line',False),('rectangle',False),('rectangle',True)])
@pytest.mark.parametrize('value',[-1,0,100])
def test_paint_shapes_are_bounded_and_preserve_parent(shape,filled,value):
    source=grid();source['data']=[100]*400;before=copy.deepcopy(source)
    edited,_=optimize_snapshot(source,[{'type':'paint','shape':shape,'points':[{'x':3,'y':2},{'x':6,'y':5}],'value':value,'width_m':.05,'filled':filled}])
    assert source==before and edited['info']==source['info']
    assert edited['data'][(20-1-2)*20+3]==value
    assert edited['data'][0]==100


def test_mask_is_independent_of_terrain_and_erasable():
    source=grid();op={'type':'keepout','shape':'rectangle','points':[{'x':3,'y':3},{'x':5,'y':5}],'value':100,'filled':True,'width_m':.05}
    edited,_=optimize_snapshot(source,[op]);assert edited['data']==source['data'] and any(edited['keepout'])
    erased,_=optimize_snapshot(edited,[{**op,'type':'paint','value':0}]);assert erased['keepout']==edited['keepout']
    clear,_=optimize_snapshot(edited,[{**op,'value':0}]);assert not any(clear['keepout'])
    assert 'keepout.pgm' in snapshot_assets(edited)['assets']


def test_candidates_do_not_edit_unknown_and_reject_non_candidates():
    source=grid();source['data'][3]=100;source['data'][4]=-1;before=copy.deepcopy(source)
    suggestions=isolated_candidates(source,2);assert len(suggestions)==1 and source==before
    op={'type':'candidate','shape':'cells','points':[{'x':3,'y':19}],'max_cells':2,'value':0}
    edited,_=optimize_snapshot(source,[op]);assert edited['data'][3]==0 and edited['data'][4]==-1
    with pytest.raises(ValueError):optimize_snapshot(source,[{**op,'points':[{'x':4,'y':19}]}])


def test_pgm_modes_comments_and_binary_whitespace():
    assert pgm_pixels(b'P2\n# comment\n2 1\n255\n0 255\n# tail')[3]==[0,255]
    assert pgm_pixels(b'P5\r\n2 1\r\n255\r\n'+bytes([10,32]))[3]==[10,32]
    assert pgm_pixels(b'P5\n1 1\n65535\n\xff\xff')[3]==[65535]
    with pytest.raises(ValueError):pgm_pixels(b'P2\n1 1\n255\n0 1')


def test_import_roundtrip_and_mask_geometry():
    snapshot=import_snapshot({'map':pair()});assert snapshot['data']==[-1,0,100,0]
    packed=snapshot_assets(snapshot)
    def exported(name):return {'filename':name+'.pgm','yaml':packed['assets'][name+'.yaml'][0].decode(),'pgm_base64':base64.b64encode(packed['assets'][name+'.pgm'][0]).decode()}
    assert import_snapshot({'map':exported('map')})['data']==snapshot['data']
    mask=pair(b'P2\n2 2\n255\n0 254 254 254','keepout.pgm')
    combined=import_snapshot({'map':pair(),'keepout':mask});assert combined['keepout']==[0,0,100,0]
    with pytest.raises(ValueError):import_snapshot({'map':pair(),'keepout':{**mask,'yaml':mask['yaml'].replace('0.05','0.1')}})


@pytest.mark.parametrize('change',[{'yaml':'!!python/object/apply:os.system [echo no]'}, {'yaml':'image: /etc/passwd\nresolution: 1\norigin: [0,0,0]'}, {'yaml':'image: https://a/map.pgm\nresolution: 1\norigin: [0,0,0]'}, {'yaml':'image: map.pgm\nmode: scale\nresolution: 1\norigin: [0,0,0]'}, {'pgm_base64':'invalid!!!'}])
def test_import_rejects_unsafe_or_invalid_files(change):
    with pytest.raises(ValueError):import_snapshot({'map':{**pair(),**change}})


def test_import_preview_save_export_and_permission(client,login):
    headers={'Authorization':f"Bearer {login('operator','operator123')}"}
    result=client.post('/api/v1/maps/import-ros',json={'name':'编辑器测试','map':pair()},headers=headers)
    assert result.status_code==201,result.text
    root='/api/v1/maps/'+result.json()['id']
    original=client.get(root+'/files/grid',headers=headers).json()
    body={'request_id':str(uuid4()),'name':'编辑版','operations':[{'type':'keepout','shape':'brush','points':[{'x':0,'y':0}],'value':100,'width_m':.01}]}
    preview=client.post(root+'/optimization-preview',json=body,headers=headers);assert preview.status_code==200,preview.text
    assert preview.json()['keepout_url'] and preview.json()['effective_keepout_url'] and preview.json()['diff_url']
    saved=client.post(root+'/derive',json=body,headers=headers);assert saved.status_code==201,saved.text
    child='/api/v1/maps/'+saved.json()['id']
    exported=client.get(child+'/export-ros',headers=headers);assert exported.status_code==200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:assert {'map.pgm','map.yaml','keepout.pgm','keepout.yaml','version.json'}<=set(archive.namelist())
    assert client.get(root+'/files/grid',headers=headers).json()==original
    readonly={'Authorization':f"Bearer {login('auditor','auditor123')}"}
    assert client.post(root+'/cleanup-candidates',json={},headers=readonly).status_code==403
    assert client.post('/api/v1/maps/import-ros',json={'name':'拒绝','map':pair()},headers=readonly).status_code==403


def test_old_vehicle_cannot_silently_ignore_keepout(client,login,monkeypatch):
    headers={'Authorization':f"Bearer {login('operator','operator123')}"}
    mask=pair(b'P2\n2 2\n255\n0 254 254 254','keepout.pgm')
    result=client.post('/api/v1/maps/import-ros',json={'name':'遮罩测试','map':pair(),'keepout':mask},headers=headers).json()
    calls=[]
    async def old_vehicle(self,path,payload=None,**kwargs):calls.append(path);return {'state':'ready'}
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',old_vehicle)
    response=client.post('/api/v1/maps/'+result['id']+'/load-navigation',json={},headers=headers)
    assert response.status_code==502 and calls==['runtime']
