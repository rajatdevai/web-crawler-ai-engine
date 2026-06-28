import requests
import time
import json

print("Submitting job...")
url = "http://localhost:8000/api/v1/crawl"
payload = {
    "url": "https://www.caeliusconsulting.com/",
    "max_pages": 5,
    "max_depth": 2,
    "respect_robots_txt": True
}

response = requests.post(url, json=payload)
data = response.json()
job_id = data.get("job_id")
print(f"Job ID: {job_id}")

print("Waiting for job to complete...")
while True:
    status_response = requests.get(f"http://localhost:8000/api/v1/jobs/{job_id}")
    status_data = status_response.json()
    status = status_data.get("status")
    print(f"Status: {status} (Crawled: {status_data.get('pages_crawled', 0)}/{status_data.get('pages_discovered', 0)})")
    
    if status in ["COMPLETED", "FAILED"]:
        break
    time.sleep(2)

print("\nFetching classified pages...")
results_response = requests.get(f"http://localhost:8000/api/v1/jobs/{job_id}/results")
results = results_response.json()
print("\n--- RESULTS ---")
print(json.dumps(results, indent=2))
