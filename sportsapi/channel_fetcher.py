#!/usr/bin/env python3
"""
SportAPI TV Channel Fetcher - Systematically fetch channels by country
Uses SportAPI7 with rate limiting (40 requests/second)
"""

import asyncio
import http.client
import json
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SportAPIChannelFetcher:
    def __init__(self, countries_path='data/geolite2_countries.json', output_path='data/channels_database.json'):
        self.countries_path = countries_path
        self.output_path = output_path
        self.rapidapi_key = os.getenv('RAPIDAPI_KEY')
        
        if not self.rapidapi_key:
            raise ValueError("RAPIDAPI_KEY not found in .env file")
        
        # Load country data
        self.countries = self._load_countries()
        
        # Initialize database structure
        self.channels_db = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'updated_at': None,
                'total_countries_processed': 0,
                'total_channels_found': 0,
                'countries_with_channels': [],
                'countries_processed': [],
                'failed_countries': [],
                'stats': {
                    'api_requests_made': 0,
                    'successful_requests': 0,
                    'failed_requests': 0,
                    'rate_limit_delays': 0
                }
            },
            'channels_by_country': {},  # ISO_CODE -> [channels]
            'all_channels': {}  # channel_id -> {id, name, countries[], logos[], etc}
        }
        
        # Load existing database if available
        self._load_existing_database()
    
    def _load_countries(self):
        """Load country mappings from geolite2_countries.json"""
        try:
            with open(self.countries_path, 'r', encoding='utf-8') as f:
                countries_data = json.load(f)
            
            # Create lookup dict: iso_code -> country_info
            countries = {}
            for country in countries_data:
                iso_code = country.get('country_iso_code', '').upper().strip()
                if iso_code and len(iso_code) == 2:  # Valid ISO2 codes
                    countries[iso_code] = {
                        'name': country.get('country_name', iso_code),
                        'continent': country.get('continent_name', 'Unknown'),
                        'is_eu': bool(country.get('is_in_european_union', 0))
                    }
            
            print(f"✅ Loaded {len(countries)} countries from {self.countries_path}")
            return countries
            
        except FileNotFoundError:
            print(f"❌ Country file {self.countries_path} not found")
            return {}
        except Exception as e:
            print(f"❌ Error loading countries: {e}")
            return {}
    
    def _load_existing_database(self):
        """Load existing database to continue from where we left off"""
        try:
            with open(self.output_path, 'r', encoding='utf-8') as f:
                existing_db = json.load(f)
            
            # Merge with existing data
            if 'metadata' in existing_db:
                processed = existing_db['metadata'].get('countries_processed', [])
                failed = existing_db['metadata'].get('failed_countries', [])
                
                self.channels_db['metadata']['countries_processed'] = processed
                self.channels_db['metadata']['failed_countries'] = failed
                self.channels_db['channels_by_country'] = existing_db.get('channels_by_country', {})
                self.channels_db['all_channels'] = existing_db.get('all_channels', {})
                
                print(f"✅ Loaded existing database: {len(processed)} countries processed, {len(failed)} failed")
            
        except FileNotFoundError:
            print(f"📁 No existing database found, starting fresh")
        except Exception as e:
            print(f"⚠️ Error loading existing database: {e}")
    
    def _save_database(self):
        """Save current state of database"""
        try:
            # Update metadata
            self.channels_db['metadata']['updated_at'] = datetime.now().isoformat()
            self.channels_db['metadata']['total_countries_processed'] = len(self.channels_db['metadata']['countries_processed'])
            self.channels_db['metadata']['total_channels_found'] = len(self.channels_db['all_channels'])
            self.channels_db['metadata']['countries_with_channels'] = [
                iso for iso, channels in self.channels_db['channels_by_country'].items() 
                if channels
            ]
            
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(self.channels_db, f, indent=2, ensure_ascii=False)
            
            print(f"💾 Database saved: {self.channels_db['metadata']['total_channels_found']} channels from {self.channels_db['metadata']['total_countries_processed']} countries")
            return True
            
        except Exception as e:
            print(f"❌ Error saving database: {e}")
            return False
    
    async def fetch_channels_for_country(self, iso_code):
        """Fetch TV channels for a specific country using SportAPI"""
        try:
            print(f"🌍 Fetching channels for {self.countries.get(iso_code, {}).get('name', iso_code)} ({iso_code})")
            
            # Rate limiting: 40 requests/second = 25ms delay
            await asyncio.sleep(0.025)  # 25ms delay
            self.channels_db['metadata']['stats']['rate_limit_delays'] += 1
            
            # Make HTTP request
            conn = http.client.HTTPSConnection("sportapi7.p.rapidapi.com")
            
            headers = {
                'x-rapidapi-key': self.rapidapi_key,
                'x-rapidapi-host': "sportapi7.p.rapidapi.com"
            }
            
            endpoint = f"/api/v1/tv/country/{iso_code}/channels"
            conn.request("GET", endpoint, headers=headers)
            
            res = conn.getresponse()
            data = res.read()
            
            self.channels_db['metadata']['stats']['api_requests_made'] += 1
            
            if res.status == 200:
                channels_data = json.loads(data.decode("utf-8"))
                self.channels_db['metadata']['stats']['successful_requests'] += 1
                
                # Process channels data
                channels = self._process_country_channels(iso_code, channels_data)
                
                print(f"✅ {iso_code}: Found {len(channels)} channels")
                return channels
                
            else:
                error_msg = data.decode("utf-8")
                print(f"⚠️ {iso_code}: HTTP {res.status} - {error_msg}")
                self.channels_db['metadata']['stats']['failed_requests'] += 1
                return []
                
        except Exception as e:
            print(f"❌ {iso_code}: Error - {e}")
            self.channels_db['metadata']['stats']['failed_requests'] += 1
            return []
        finally:
            try:
                conn.close()
            except:
                pass
    
    def _process_country_channels(self, iso_code, channels_data):
        """Process channels data for a country"""
        channels = []
        country_info = self.countries.get(iso_code, {})
        
        # Handle different response formats
        if isinstance(channels_data, dict):
            # Could be {"channels": [...]} or {"data": [...]} or direct channel list
            channel_list = (
                channels_data.get('channels', []) or 
                channels_data.get('data', []) or 
                channels_data.get('results', []) or
                (channels_data if isinstance(channels_data, list) else [])
            )
        elif isinstance(channels_data, list):
            channel_list = channels_data
        else:
            print(f"⚠️ {iso_code}: Unexpected data format: {type(channels_data)}")
            return []
        
        if not channel_list:
            print(f"📺 {iso_code}: No channels found in response")
            return []
        
        for channel_data in channel_list:
            if not isinstance(channel_data, dict):
                continue
                
            # Extract channel information
            channel_id = channel_data.get('id') or channel_data.get('channel_id')
            channel_name = (
                channel_data.get('name') or 
                channel_data.get('channel_name') or 
                channel_data.get('title') or
                f"Channel {channel_id}"
            )
            
            if not channel_id:
                continue
            
            # Create channel info
            channel_info = {
                'id': channel_id,
                'name': channel_name,
                'country_code': iso_code,
                'country_name': country_info.get('name', iso_code),
                'continent': country_info.get('continent', 'Unknown'),
                'is_eu': country_info.get('is_eu', False),
                'logo': channel_data.get('logo') or channel_data.get('image'),
                'website': channel_data.get('website') or channel_data.get('url'),
                'description': channel_data.get('description'),
                'first_discovered': datetime.now().isoformat()
            }
            
            # Add to country channels
            channels.append(channel_info)
            
            # Add to global channels database
            channel_str_id = str(channel_id)
            if channel_str_id in self.channels_db['all_channels']:
                # Channel already exists, add country to list
                existing_countries = self.channels_db['all_channels'][channel_str_id].get('countries', [])
                if iso_code not in existing_countries:
                    existing_countries.append(iso_code)
                    self.channels_db['all_channels'][channel_str_id]['countries'] = existing_countries
            else:
                # New channel
                self.channels_db['all_channels'][channel_str_id] = {
                    'id': channel_id,
                    'name': channel_name,
                    'countries': [iso_code],
                    'logos': [channel_info['logo']] if channel_info['logo'] else [],
                    'websites': [channel_info['website']] if channel_info['website'] else [],
                    'first_discovered': channel_info['first_discovered']
                }
        
        # Store channels for this country
        self.channels_db['channels_by_country'][iso_code] = channels
        return channels
    
    async def fetch_all_countries(self, start_from=None, max_countries=None):
        """Fetch channels for all countries with progress tracking"""
        processed = self.channels_db['metadata']['countries_processed']
        failed = self.channels_db['metadata']['failed_countries']
        
        # Get list of countries to process
        countries_to_process = []
        for iso_code in sorted(self.countries.keys()):
            if iso_code not in processed and iso_code not in failed:
                countries_to_process.append(iso_code)
        
        # Apply start_from filter
        if start_from:
            start_from = start_from.upper()
            try:
                start_index = countries_to_process.index(start_from)
                countries_to_process = countries_to_process[start_index:]
            except ValueError:
                print(f"⚠️ Start country '{start_from}' not found, processing all remaining")
        
        # Apply max_countries limit
        if max_countries:
            countries_to_process = countries_to_process[:max_countries]
        
        print(f"\n🚀 Starting channel fetching for {len(countries_to_process)} countries")
        print(f"📊 Already processed: {len(processed)}, Failed: {len(failed)}")
        print(f"⏱️ Estimated time: ~{len(countries_to_process) * 0.3:.1f} seconds (with rate limiting)")
        print(f"💾 Progress will be saved after every 10 countries")
        print("=" * 60)
        
        start_time = time.time()
        
        for i, iso_code in enumerate(countries_to_process, 1):
            try:
                # Fetch channels for this country
                channels = await self.fetch_channels_for_country(iso_code)
                
                # Mark as processed
                self.channels_db['metadata']['countries_processed'].append(iso_code)
                
                # Show progress
                elapsed = time.time() - start_time
                remaining = len(countries_to_process) - i
                eta = (elapsed / i) * remaining if i > 0 else 0
                
                print(f"📈 Progress: {i}/{len(countries_to_process)} ({i/len(countries_to_process)*100:.1f}%) | ETA: {eta:.1f}s")
                
                # Save progress every 10 countries
                if i % 10 == 0:
                    self._save_database()
                    print(f"💾 Progress saved at {i}/{len(countries_to_process)} countries")
                
            except Exception as e:
                print(f"❌ Failed to process {iso_code}: {e}")
                self.channels_db['metadata']['failed_countries'].append(iso_code)
        
        # Final save
        self._save_database()
        self._print_final_stats()
    
    def _print_final_stats(self):
        """Print final statistics"""
        stats = self.channels_db['metadata']['stats']
        
        print("\n" + "=" * 60)
        print("🎯 FINAL STATISTICS")
        print("=" * 60)
        print(f"🌍 Countries processed: {self.channels_db['metadata']['total_countries_processed']}")
        print(f"📺 Total channels discovered: {self.channels_db['metadata']['total_channels_found']}")
        print(f"🎯 Countries with channels: {len(self.channels_db['metadata']['countries_with_channels'])}")
        print(f"❌ Failed countries: {len(self.channels_db['metadata']['failed_countries'])}")
        print(f"📡 API requests made: {stats['api_requests_made']}")
        print(f"✅ Successful requests: {stats['successful_requests']}")
        print(f"❌ Failed requests: {stats['failed_requests']}")
        print(f"⏱️ Rate limit delays: {stats['rate_limit_delays']}")
        
        if stats['api_requests_made'] > 0:
            success_rate = (stats['successful_requests'] / stats['api_requests_made']) * 100
            print(f"📈 Success rate: {success_rate:.1f}%")
        
        # Top countries by channel count
        if self.channels_db['channels_by_country']:
            country_counts = [
                (iso, len(channels)) 
                for iso, channels in self.channels_db['channels_by_country'].items() 
                if channels
            ]
            country_counts.sort(key=lambda x: x[1], reverse=True)
            
            print(f"\n🏆 Top countries by channel count:")
            for i, (iso, count) in enumerate(country_counts[:10], 1):
                country_name = self.countries.get(iso, {}).get('name', iso)
                print(f"   {i:2d}. {country_name} ({iso}): {count} channels")


async def main():
    import sys
    
    fetcher = SportAPIChannelFetcher()
    
    # Parse command line arguments
    start_from = None
    max_countries = None
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i].lower()
        
        if arg == '--start-from' and i + 1 < len(sys.argv):
            start_from = sys.argv[i + 1]
            i += 2
        elif arg == '--max' and i + 1 < len(sys.argv):
            max_countries = int(sys.argv[i + 1])
            i += 2
        elif arg == 'help':
            print_help()
            return
        else:
            i += 1
    
    # Start fetching
    await fetcher.fetch_all_countries(start_from=start_from, max_countries=max_countries)


def print_help():
    print("🌍 SportAPI TV Channel Fetcher")
    print("=" * 40)
    print("Systematically fetch TV channels by country using SportAPI7")
    print("")
    print("Usage:")
    print("  python sportapi_channel_fetcher.py [options]")
    print("")
    print("Options:")
    print("  --start-from <ISO2>  Start from specific country code (e.g., US, GB)")
    print("  --max <number>       Maximum number of countries to process")
    print("")
    print("Examples:")
    print("  python sportapi_channel_fetcher.py                    # Process all countries")
    print("  python sportapi_channel_fetcher.py --max 10          # Process first 10")
    print("  python sportapi_channel_fetcher.py --start-from GB   # Start from GB")
    print("  python sportapi_channel_fetcher.py --start-from US --max 5  # Start from US, max 5")
    print("")
    print("Features:")
    print("  ✅ Rate limiting (40 requests/second)")
    print("  ✅ Progress saving every 10 countries")
    print("  ✅ Resume from where you left off")
    print("  ✅ Comprehensive error handling")
    print("  ✅ Detailed statistics and progress tracking")


if __name__ == '__main__':
    asyncio.run(main())