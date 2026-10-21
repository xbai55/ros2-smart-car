"""Local acceptance fixture; never connects to a vehicle."""
import asyncio,sys,time
from fastapi import FastAPI,WebSocket,Request
from fastapi.responses import Response,StreamingResponse
app=FastAPI()
@app.get('/api/status')
def status():
    return {'mode':'stop','network':'connected','updated_at':time.time(),'emergency_stop':False,
            'lidar':{'ok':True},'odom':{'ok':True},'tf':{'ok':True},'motion_settings':{'turn_speed':.15,'max_laser_range':3.}}
@app.post('/api/mapping/settings')
async def settings(request:Request):return {'ok':True,'settings':await request.json()}
@app.get('/api/video')
def video():return Response(b'fake-frame',media_type='image/jpeg')
@app.get('/video_feed')
def stream():
    async def parts():yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\nfixture\r\n'
    return StreamingResponse(parts(),media_type='multipart/x-mixed-replace; boundary=frame')
@app.websocket('/ws/status')
async def socket(ws:WebSocket):
    await ws.accept()
    try:
        while True:await ws.send_json(status());await asyncio.sleep(.1)
    except Exception:pass
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
