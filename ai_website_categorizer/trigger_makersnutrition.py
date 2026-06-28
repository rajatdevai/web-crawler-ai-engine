import requests
import time
import json
import os

def main():
    print("Submitting job for https://www.makersnutrition.com/ ...")
    url = "http://localhost:8000/api/v1/crawl"
    payload = {
        "url": "https://www.makersnutrition.com/",
        "max_pages": 120,
        "max_depth": 3,
        "respect_robots_txt": True
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Error submitting job: {e}")
        return
        
    data = response.json()
    job_id = data.get("job_id")
    print(f"Job ID: {job_id}")
    
    print("Waiting for job to complete...")
    status = "PENDING"
    while True:
        try:
            status_response = requests.get(f"http://localhost:8000/api/v1/jobs/{job_id}")
            status_response.raise_for_status()
            status_data = status_response.json()
            status = status_data.get("status")
            pages_crawled = status_data.get("pages_crawled", 0)
            pages_discovered = status_data.get("pages_discovered", 0)
            print(f"Status: {status} (Crawled: {pages_crawled}/{pages_discovered})")
        except Exception as e:
            print(f"Error fetching job status: {e}")
            
        if status in ["COMPLETED", "FAILED"]:
            break
        time.sleep(5)
        
    print("\nFetching results...")
    try:
        results_response = requests.get(f"http://localhost:8000/api/v1/jobs/{job_id}/results")
        results_response.raise_for_status()
        results = results_response.json()
    except Exception as e:
        print(f"Error fetching results: {e}")
        return

    # Write raw results
    output_json_path = "makers_nutrition_results.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Raw results written to {output_json_path}")

    # Generate a beautiful Markdown report grouping categories
    generate_report(results, job_id)

def generate_report(results, job_id):
    # Group URLs by category
    groups = {}
    
    # Results is a list of pages
    pages = results.get("pages", []) if isinstance(results, dict) else results
    for page in pages:
        url = page.get("url")
        class_res = page.get("classification_result") or {}
        category = class_res.get("final_category", "UNCATEGORIZED")
        
        # Subgroup by page type if possible based on URL patterns
        page_type = "Informational Pages"
        if "/blog/" in url:
            page_type = "Blogs"
        elif "/resources/" in url:
            page_type = "Resources"
        elif "/private-label/" in url:
            page_type = "Private Label / Product Pages"
        elif "manufacturer" in url or "manufacturing" in url:
            page_type = "Service / Manufacturing Pages"
            
        groups.setdefault(category, {}).setdefault(page_type, []).append(url)
        
    report = []
    report.append("# AI Website Categorization Report: Makers Nutrition")
    report.append(f"**Job ID:** `{job_id}`  ")
    report.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    report.append("\nThis report lists the pages crawled and categorized by the AI categorization prototype engine.\n")
    
    for category, sub_groups in sorted(groups.items()):
        report.append(f"## Category: {category}")
        for page_type, urls in sorted(sub_groups.items()):
            report.append(f"### {page_type}")
            for url in sorted(urls):
                report.append(f"- {url}")
            report.append("")
            
    output_md_path = "makers_nutrition_report.md"
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"Formatted report written to {output_md_path}")

if __name__ == "__main__":
    main()
