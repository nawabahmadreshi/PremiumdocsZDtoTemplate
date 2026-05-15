import json
import re
import requests
from typing import List, Dict
from config import TC_EMAILS, CS_EMAILS

def send_slack_notification(webhook_url: str, event: Dict, config: Dict = None):
    """
    Send a formatted notification to Slack about a tracking event.
    """
    try:
        user_email = (event.get("User email") or event.get("user_email") or "anonymous").lower()
        article_title = event.get("Article title") or event.get("article_title") or "Unknown Article"
        domain = (event.get("Email domain") or event.get("email_domain") or "unknown").lower()
        
        is_external = domain != "aquera.com"
        tag = "🟢 [EXTERNAL]" if is_external else "🔵 [INTERNAL]"
        
        # Slack payload
        payload = {
            "text": config.get('slack_custom_text', 'New Documentation Activity!') if config else 'New Documentation Activity!',
            "attachments": [
                {
                    "color": "#10b981" if is_external else "#6366f1",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{tag} {article_title}*"
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Viewer:*\n{user_email}"},
                                {"type": "mrkdwn", "text": f"*Source Domain:*\n{domain}"}
                            ]
                        }
                    ]
                }
            ]
        }
        
        # Add thumbnail if provided
        if config and config.get('slack_image_url'):
            payload["attachments"][0]["thumb_url"] = config.get('slack_image_url')

        requests.post(webhook_url, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"Slack Notification Error: {e}")
        return False

def parse_tracking_logs(comments: List[Dict]) -> List[Dict]:
    """
    Extract JSON tracking events from Zendesk comments using flexible markers.
    """
    events = []
    for i, comment in enumerate(comments):
        body = comment.get('body', '')
        if not body: continue
        
        try:
            json_str = ""
            # Strategy 1: Triple backticks
            if "```json" in body:
                start_marker = "```json"
                end_marker = "```"
                start_idx = body.find(start_marker) + len(start_marker)
                end_idx = body.find(end_marker, start_idx)
                json_str = body[start_idx:end_idx].strip()
            
            # Strategy 2: HTML Pre tags (found in archived logs)
            elif "<pre>" in body:
                start_marker = "<pre>"
                end_marker = "</pre>"
                start_idx = body.find(start_marker) + len(start_marker)
                end_idx = body.find(end_marker, start_idx)
                json_str = body[start_idx:end_idx].strip()
            
            # Strategy 3: "Raw JSON" text block
            elif "Raw JSON" in body:
                start_idx = body.find("Raw JSON") + len("Raw JSON")
                start_brace = body.find("{", start_idx)
                if start_brace != -1:
                    end_brace = body.rfind("}")
                    if end_brace > start_brace:
                        json_str = body[start_brace:end_brace+1].strip()

            if json_str:
                # Clean HTML tags if they leaked into the JSON string (Zendesk sometimes auto-links emails/URLs)
                json_str = re.sub(r'<[^>]+>', '', json_str)
                # Remove common problematic whitespace
                json_str = json_str.replace("&nbsp;", " ").replace("\xa0", " ")
                
                data = json.loads(json_str)
                
                # Basic validation
                if any(k in data.keys() for k in ["article id", "article_id", "Article id"]):
                    data['log_id'] = comment.get('id')
                    # Normalize timestamp
                    data['log_timestamp'] = data.get('log_timestamp') or data.get('timestamp') or data.get('Timestamp') or comment.get('created_at')
                    
                    user_email = (data.get("User email") or data.get("user_email") or "anonymous").lower()
                    data['user_email'] = user_email # Ensure normalized key
                    data['is_cs'] = user_email in CS_EMAILS
                    data['is_tc'] = user_email in TC_EMAILS
                    
                    # Normalize other common fields for the UI
                    data['email_domain'] = data.get("Email domain") or data.get("email_domain") or data.get("Domain") or "unknown"
                    data['article_title'] = data.get("Article title") or data.get("article_title") or data.get("Article") or "Unknown Article"
                    
                    events.append(data)
        except Exception:
            continue
    return events

def calculate_stats(events: List[Dict]) -> Dict:
    """
    Generate summary statistics from tracking events, including CS and TC team views.
    """
    if not events:
        return {
            "total_views": 0,
            "unique_users": 0,
            "top_articles": [],
            "top_domains": [],
            "external_vs_internal": {"Aquera": 0, "External": 0, "Unique External": 0, "TC Views": 0, "CS Views": 0},
            "views_over_time": []
        }
        
    stats = {
        "total_views": 0,
        "unique_users": 0,
        "top_articles": {},
        "top_domains": {},
        "top_cities": {},
        "top_countries": {},
        "external_vs_internal": {"Aquera": 0, "External": 0, "Unique External": 0, "TC Views": 0, "CS Views": 0},
        "views_over_time": {}
    }
    
    unique_user_emails = set()
    unique_external_emails = set()
    processed_log_ids = set()
    deduplicated_events = []
    
    timeline_total = {}
    timeline_external = {}
    
    for event in events:
        log_id = event.get("log_id")
        if log_id and log_id in processed_log_ids:
            continue
        if log_id: processed_log_ids.add(log_id)
        
        user_email = (event.get("User email") or event.get("user_email") or "anonymous").lower()
        domain = (event.get("Email domain") or event.get("email_domain") or "unknown").lower().strip()
        
        deduplicated_events.append(event)
        if user_email != "anonymous":
            unique_user_emails.add(user_email)
            
        # Classification
        is_external = domain != "aquera.com"
        if is_external:
            stats["external_vs_internal"]["External"] += 1
            if user_email != "anonymous":
                unique_external_emails.add(user_email)
        else:
            stats["external_vs_internal"]["Aquera"] += 1
            if user_email in CS_EMAILS:
                stats["external_vs_internal"]["CS Views"] += 1
            if user_email in TC_EMAILS:
                stats["external_vs_internal"]["TC Views"] += 1
                
        # Article stats
        art_title = event.get("Article title") or event.get("article_title") or "Unknown Article"
        stats["top_articles"][art_title] = stats["top_articles"].get(art_title, 0) + 1
        
        # Domain stats
        stats["top_domains"][domain] = stats["top_domains"].get(domain, 0) + 1
        
        # Geo stats
        city = event.get("city")
        if city: stats["top_cities"][city] = stats["top_cities"].get(city, 0) + 1
        
        country = event.get("country")
        if country: stats["top_countries"][country] = stats["top_countries"].get(country, 0) + 1
        
        # Timeline stats
        ts = event.get('log_timestamp')
        if ts:
            date = ts[:10] # YYYY-MM-DD
            timeline_total[date] = timeline_total.get(date, 0) + 1
            if is_external:
                timeline_external[date] = timeline_external.get(date, 0) + 1

    # Final counts
    stats["total_views"] = len(deduplicated_events)
    stats["unique_users"] = len(unique_user_emails)
    stats["external_vs_internal"]["Unique External"] = len(unique_external_emails)
    
    # Sort top lists
    stats["top_articles"] = [{"title": k, "count": v} for k, v in sorted(stats["top_articles"].items(), key=lambda x: x[1], reverse=True)[:5]]
    stats["top_domains"] = [{"domain": k, "count": v} for k, v in sorted(stats["top_domains"].items(), key=lambda x: x[1], reverse=True)[:5]]
    stats["top_cities"] = [{"city": k, "count": v} for k, v in sorted(stats["top_cities"].items(), key=lambda x: x[1], reverse=True)[:5]]
    stats["top_countries"] = [{"country": k, "count": v} for k, v in sorted(stats["top_countries"].items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Timeline series
    all_dates = sorted(list(set(timeline_total.keys()) | set(timeline_external.keys())))
    views_series = []
    for d in all_dates:
        views_series.append({"date": d, "count": timeline_total.get(d, 0), "group": "Total Views"})
        views_series.append({"date": d, "count": timeline_external.get(d, 0), "group": "External Views"})
    stats["views_over_time"] = views_series
    
    return stats
