import asyncio
import schedule
import time
from datetime import datetime, timezone
import os
import sys
import pytz

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from background_checker import BackgroundChecker

async def run_background_check():
    """Run the background check"""
    try:
        checker = BackgroundChecker()
        await checker.check_all_subscriptions()
    except Exception as e:
        print(f"Error during scheduled background check: {str(e)}")

def run_async_check():
    """Wrapper to run async function in schedule"""
    asyncio.run(run_background_check())

def setup_scheduler():
    """Setup the daily scheduler with timezone support"""
    # Get timezone configuration
    timezone_name = os.getenv('TIMEZONE', 'UTC')
    try:
        user_timezone = pytz.timezone(timezone_name)
    except pytz.exceptions.UnknownTimeZoneError:
        user_timezone = pytz.UTC
        timezone_name = 'UTC'
    
    # Get custom schedule time from environment variable
    schedule_time = os.getenv('SCHEDULE_TIME', '09:00')
    schedule_times = os.getenv('SCHEDULE_TIMES') or schedule_time
    
    # Support multiple schedule times (comma-separated)
    times = [time.strip() for time in schedule_times.split(',')]
    
    
    scheduled_times = []
    for time_str in times:
        try:
            # Validate time format
            time_obj = datetime.strptime(time_str, '%H:%M').time()
            
            if timezone_name == 'UTC':
                # If timezone is UTC, use time directly
                utc_time_str = time_str
                schedule.every().day.at(utc_time_str).do(run_async_check)
                scheduled_times.append(f"{time_str} UTC")
            else:
                # Convert local time to UTC for the scheduler
                # Create a naive datetime object for today and localize it
                now_local = datetime.now(user_timezone)
                today_local = now_local.date()
                
                # Create naive datetime and then localize to user timezone
                naive_datetime = datetime.combine(today_local, time_obj)
                scheduled_local = user_timezone.localize(naive_datetime)
                scheduled_utc = scheduled_local.astimezone(pytz.UTC)
                utc_time_str = scheduled_utc.strftime('%H:%M')
                
                # Schedule using UTC time
                schedule.every().day.at(utc_time_str).do(run_async_check)
                
                scheduled_times.append(f"{time_str} {timezone_name}")
            
        except ValueError:
            print(f"Invalid time format: {time_str}. Using default 09:00")
            schedule.every().day.at("09:00").do(run_async_check)
            scheduled_times.append("09:00 UTC (fallback)")
        except Exception as e:
            print(f"Error setting up schedule for {time_str}: {str(e)}")
            schedule.every().day.at("09:00").do(run_async_check)
            scheduled_times.append("09:00 UTC (fallback)")
    
    
    return True

def run_scheduler():
    """Run the scheduler continuously"""
    setup_scheduler()
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
            
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Scheduler error: {str(e)}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='YouTube Subscription Scheduler')
    parser.add_argument('--run-once', action='store_true', help='Run check once and exit')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon (default)')
    
    args = parser.parse_args()
    
    if args.run_once:
        asyncio.run(run_background_check())
    else:
        run_scheduler()