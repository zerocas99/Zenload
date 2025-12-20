from pymongo import MongoClient
import os
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Connect to MongoDB
client = MongoClient(os.getenv('MONGODB_URI'))
db = client.zenload

def print_separator():
    print("\n" + "="*50 + "\n")

def print_basic_stats():
    """Print basic database statistics"""
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    one_month_ago = now - timedelta(days=30)

    users_count = db.user_settings.count_documents({})
    groups_count = db.group_settings.count_documents({})
    
    print("📊 Database Statistics:")
    print(f"Total Users: {users_count}")
    print(f"Total Groups: {groups_count}")
    
    # Activity Stats
    new_users = db.user_settings.count_documents({"created_at": {"$gte": one_week_ago}})
    active_users = db.user_settings.count_documents({"updated_at": {"$gte": one_week_ago}})
    inactive_users = db.user_settings.count_documents({"updated_at": {"$lt": one_month_ago}})
    
    print(f"\nActivity Metrics (Last 7 days):")
    print(f"New Users: {new_users}")
    print(f"Active Users: {active_users}")
    print(f"Inactive Users (30+ days): {inactive_users}")

def print_user_details():
    """Print detailed user information"""
    users_count = db.user_settings.count_documents({})
    
    print("👤 User Details:")
    premium_users = db.user_settings.count_documents({"is_premium": True})
    premium_percentage = (premium_users / users_count * 100) if users_count > 0 else 0
    print(f"Premium Users: {premium_users} ({premium_percentage:.1f}%)")
    
    # Profile Completeness
    complete_profiles = db.user_settings.count_documents({
        "username": {"$ne": None},
        "first_name": {"$ne": None},
        "last_name": {"$ne": None}
    })
    profile_percentage = (complete_profiles / users_count * 100) if users_count > 0 else 0
    print(f"Complete Profiles: {complete_profiles} ({profile_percentage:.1f}%)")
    
    # Language distribution
    print("\nLanguage Distribution:")
    languages = db.user_settings.aggregate([
        {"$group": {"_id": "$language", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ])
    for lang in languages:
        percentage = (lang['count'] / users_count * 100) if users_count > 0 else 0
        print(f"- {lang['_id'] or 'Not Set'}: {lang['count']} users ({percentage:.1f}%)")

def print_download_stats():
    """Print download statistics from user_activity collection"""
    print("📊 Download Statistics:")
    
    # Total downloads
    total_downloads = db.user_activity.count_documents({"action_type": "download_complete"})
    successful_downloads = db.user_activity.count_documents({
        "action_type": "download_complete",
        "status": "success"
    })
    failed_downloads = db.user_activity.count_documents({
        "action_type": "download_complete",
        "status": "failed"
    })
    
    success_rate = (successful_downloads / total_downloads * 100) if total_downloads > 0 else 0
    print(f"Total Downloads: {total_downloads}")
    print(f"Successful: {successful_downloads} ({success_rate:.1f}%)")
    print(f"Failed: {failed_downloads} ({100-success_rate:.1f}%)")
    
    # Platform statistics
    print("\nPlatform Distribution:")
    platform_stats = db.user_activity.aggregate([
        {"$match": {"action_type": "download_complete"}},
        {"$group": {
            "_id": {
                "platform": "$platform",
                "status": "$status"
            },
            "count": {"$sum": 1},
            "avg_time": {"$avg": "$processing_time"}
        }},
        {"$sort": {"count": -1}}
    ])
    
    platform_data = defaultdict(lambda: {"success": 0, "failed": 0, "avg_time": 0})
    for stat in platform_stats:
        platform = stat["_id"]["platform"]
        status = stat["_id"]["status"]
        count = stat["count"]
        avg_time = stat["avg_time"] or 0
        
        platform_data[platform][status] = count
        platform_data[platform]["avg_time"] = avg_time
    
    for platform, data in platform_data.items():
        total = data["success"] + data["failed"]
        success_rate = (data["success"] / total * 100) if total > 0 else 0
        print(f"\n{platform.capitalize()}:")
        print(f"  Total: {total}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Average Processing Time: {data['avg_time']:.1f}s")

def print_user_activity_stats():
    """Print detailed user activity statistics"""
    print("👥 User Activity Analysis:")
    
    # Most active users
    print("\nMost Active Users (Top 5):")
    active_users = db.user_activity.aggregate([
        {"$group": {
            "_id": "$user_id",
            "download_count": {"$sum": 1},
            "success_count": {
                "$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}
            },
            "last_activity": {"$max": "$timestamp"}
        }},
        {"$sort": {"download_count": -1}},
        {"$limit": 5}
    ])
    
    for user in active_users:
        user_settings = db.user_settings.find_one({"user_id": user["_id"]})
        username = user_settings.get("username", "Unknown") if user_settings else "Unknown"
        success_rate = (user["success_count"] / user["download_count"] * 100) if user["download_count"] > 0 else 0
        print(f"User @{username}:")
        print(f"  Downloads: {user['download_count']}")
        print(f"  Success Rate: {success_rate:.1f}%")
        print(f"  Last Active: {user['last_activity'].strftime('%Y-%m-%d %H:%M:%S')}")

def print_quality_stats():
    """Print statistics about quality preferences and file types"""
    print("🎯 Quality & Format Statistics:")
    
    # Quality selection stats
    print("\nQuality Preferences:")
    quality_stats = db.user_activity.aggregate([
        {"$match": {"action_type": "quality_select"}},
        {"$group": {
            "_id": "$quality",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ])
    
    total_quality_selections = db.user_activity.count_documents({"action_type": "quality_select"})
    for stat in quality_stats:
        percentage = (stat["count"] / total_quality_selections * 100) if total_quality_selections > 0 else 0
        print(f"{stat['_id']}: {stat['count']} ({percentage:.1f}%)")
    
    # File type stats
    print("\nFile Types:")
    file_stats = db.user_activity.aggregate([
        {"$match": {
            "action_type": "download_complete",
            "status": "success"
        }},
        {"$group": {
            "_id": "$file_type",
            "count": {"$sum": 1},
            "avg_size": {"$avg": "$file_size"}
        }},
        {"$sort": {"count": -1}}
    ])
    
    for stat in file_stats:
        avg_size_mb = (stat["avg_size"] / (1024 * 1024)) if stat["avg_size"] else 0
        print(f"{stat['_id']}: {stat['count']} files (avg size: {avg_size_mb:.1f}MB)")

def print_group_stats():
    """Print group usage statistics"""
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    groups_count = db.group_settings.count_documents({})
    
    print("👥 Group Analysis:")
    if groups_count > 0:
        active_groups = db.group_settings.count_documents({"updated_at": {"$gte": one_week_ago}})
        group_percentage = (active_groups / groups_count * 100)
        print(f"Active Groups (7 days): {active_groups} ({group_percentage:.1f}%)")
        
        # Admin Distribution
        admin_counts = defaultdict(int)
        for group in db.group_settings.find():
            admin_counts[group['admin_id']] += 1
        
        multi_admin_count = sum(1 for count in admin_counts.values() if count > 1)
        if multi_admin_count > 0:
            print(f"\nAdmins managing multiple groups: {multi_admin_count}")

def print_data_quality():
    """Print data quality checks"""
    print("🔍 Data Quality Check:")
    
    # Check for potential duplicates based on username
    username_duplicates = db.user_settings.aggregate([
        {"$match": {"username": {"$ne": None}}},
        {"$group": {"_id": "$username", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}
    ])
    
    duplicate_count = 0
    for dup in username_duplicates:
        duplicate_count += dup['count'] - 1
    
    if duplicate_count > 0:
        print(f"⚠️ Found {duplicate_count} potential duplicate user entries")
        print("Consider running a cleanup script to merge or verify these entries")
    else:
        print("✅ No duplicate users found")

def main():
    """Main function to run all statistics"""
    print_basic_stats()
    print_separator()
    
    print_user_details()
    print_separator()
    
    print_download_stats()
    print_separator()
    
    print_user_activity_stats()
    print_separator()
    
    print_quality_stats()
    print_separator()
    
    print_group_stats()
    print_separator()
    
    print_data_quality()

if __name__ == "__main__":
    try:
        main()
    finally:
        client.close()
