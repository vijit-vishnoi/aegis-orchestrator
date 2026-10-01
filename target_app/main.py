import time
from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()

                          
REQUEST_COUNT = Counter("app_requests_total", "Total app requests", ["endpoint"])
REQUEST_LATENCY = Histogram("app_request_latency_seconds", "Request latency", ["endpoint"])

@app.get("/metrics")
def metrics():
                                             
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/")
def read_root():
    REQUEST_COUNT.labels(endpoint="/").inc()
    return {"status": "ok", "app": "target_app"}

@app.get("/chaos/cpu")
async def chaos_cpu():
    REQUEST_COUNT.labels(endpoint="/chaos/cpu").inc()
    print("[WARN] CPU Chaos endpoint hit. Burning CPU cycles for 30 seconds...")
    
                                                
    end_time = time.time() + 30
    while time.time() < end_time:
        _ = [i * i for i in range(10000)]
        
    return {"status": "cpu_spiked", "duration": 30}

@app.get("/chaos/error")
def chaos_error():
    REQUEST_COUNT.labels(endpoint="/chaos/error").inc()
                                                                   
    print("[FATAL ERROR] Simulated catastrophic failure in database connection pool!")
    return {"status": "error_logged"}
