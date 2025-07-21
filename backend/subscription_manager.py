import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Subscription:
    id: str
    channel_url: str
    channel_name: str
    user_email: str
    created_at: str
    last_checked: Optional[str] = None
    active: bool = True

class SubscriptionManager:
    def __init__(self, data_file: str = None):
        if data_file is None:
            # Simple approach: Use DATA_DIR environment variable or default to ./data
            data_dir = os.getenv('DATA_DIR', 'data')
            self.data_file = Path(data_dir) / "subscriptions.json"
        else:
            self.data_file = Path(data_file)
        
        # Ensure the data directory exists
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Create empty subscriptions file if it doesn't exist"""
        if not self.data_file.exists():
            self._save_data([])
    
    def _load_data(self) -> List[Dict]:
        """Load subscriptions from JSON file"""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def _save_data(self, subscriptions: List[Dict]):
        """Save subscriptions to JSON file"""
        # Directory is already created in __init__, no need to recreate
        with open(self.data_file, 'w') as f:
            json.dump(subscriptions, f, indent=2)
    
    def add_subscription(self, channel_url: str, channel_name: str, user_email: str) -> Subscription:
        """Add a new subscription"""
        subscription = Subscription(
            id=str(uuid.uuid4()),
            channel_url=channel_url,
            channel_name=channel_name,
            user_email=user_email,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        subscriptions = self._load_data()
        subscriptions.append(asdict(subscription))
        self._save_data(subscriptions)
        
        return subscription
    
    def get_subscriptions(self) -> List[Subscription]:
        """Get all active subscriptions"""
        data = self._load_data()
        return [Subscription(**sub) for sub in data if sub.get('active', True)]
    
    def get_subscription_by_id(self, subscription_id: str) -> Optional[Subscription]:
        """Get subscription by ID"""
        data = self._load_data()
        for sub_data in data:
            if sub_data['id'] == subscription_id:
                return Subscription(**sub_data)
        return None
    
    def update_last_checked(self, subscription_id: str, last_checked: str):
        """Update last checked timestamp for a subscription"""
        data = self._load_data()
        for sub in data:
            if sub['id'] == subscription_id:
                sub['last_checked'] = last_checked
                break
        self._save_data(data)
    
    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete a subscription"""
        data = self._load_data()
        original_length = len(data)
        data = [sub for sub in data if sub['id'] != subscription_id]
        
        if len(data) < original_length:
            self._save_data(data)
            return True
        return False
    
    def get_subscriptions_by_email(self, email: str) -> List[Subscription]:
        """Get all subscriptions for a specific email"""
        data = self._load_data()
        return [Subscription(**sub) for sub in data 
                if sub.get('user_email') == email and sub.get('active', True)]
    
    def delete_subscription_by_email_and_channel(self, email: str, channel_url: str) -> bool:
        """Delete a subscription by email and channel URL"""
        data = self._load_data()
        original_length = len(data)
        data = [sub for sub in data if not (
            sub.get('user_email') == email and sub.get('channel_url') == channel_url
        )]
        
        if len(data) < original_length:
            self._save_data(data)
            return True
        return False
    
    def subscription_exists(self, email: str, channel_url: str) -> bool:
        """Check if a subscription already exists for email and channel"""
        data = self._load_data()
        for sub in data:
            if (sub.get('user_email') == email and 
                sub.get('channel_url') == channel_url and 
                sub.get('active', True)):
                return True
        return False
    
    def get_all_unique_emails(self) -> List[str]:
        """Get all unique email addresses with active subscriptions"""
        data = self._load_data()
        emails = set()
        for sub in data:
            if sub.get('active', True) and sub.get('user_email'):
                emails.add(sub['user_email'])
        return list(emails)