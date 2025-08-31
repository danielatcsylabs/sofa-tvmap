#!/usr/bin/env python3
"""
TV Channel Database System - Build and manage local channel cache
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from sofascore_wrapper.match import Match
from sofascore_wrapper.api import SofascoreAPI


class ChannelDatabase:
    def __init__(self, db_path='data/channels_database.json', countries_path='data/geolite2_countries.json'):
        self.db_path = db_path
        self.countries_path = countries_path
        self.api = SofascoreAPI()
        
        # Load country mapping
        self.countries = self._load_countries()
        
        # Initialize database
        self.channels_db = {
            'metadata': {
                'created_at': None,
                'updated_at': None,
                'total_channels': 0,
                'countries_with_channels': [],
                'stats': {
                    'matches_processed': 0,
                    'channels_discovered': 0,
                    'api_requests_saved': 0,
                    'cache_hit_rate': 0.0
                }
            },
            'channels': {},  # channel_id -> {id, name, countries[], first_seen}
            'country_channels': {}  # country_code -> [channel_ids]
        }
        
        # Load existing database
        self._load_database()
    
    def _load_countries(self):
        """Load country mappings from geolite2_countries.json"""
        try:
            with open(self.countries_path, 'r', encoding='utf-8') as f:
                countries_data = json.load(f)
            
            # Create lookup dict: iso_code -> country_info
            countries = {}
            for country in countries_data:
                iso_code = country.get('country_iso_code', '').upper()
                if iso_code:
                    countries[iso_code] = {
                        'name': country.get('country_name', iso_code),
                        'continent': country.get('continent_name', 'Unknown'),
                        'is_eu': bool(country.get('is_in_european_union', 0))
                    }
            
            print(f"✅ Loaded {len(countries)} country mappings")
            return countries
            
        except FileNotFoundError:
            print(f"⚠️ Country file {self.countries_path} not found, using basic mapping")
            return {}
        except Exception as e:
            print(f"❌ Error loading countries: {e}")
            return {}
    
    def _load_database(self):
        """Load existing channel database"""
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self.channels_db = json.load(f)
            
            print(f"✅ Loaded existing database: {self.channels_db['metadata']['total_channels']} channels")
            return True
            
        except FileNotFoundError:
            print(f"📁 Database file {self.db_path} not found, starting fresh")
            return False
        except Exception as e:
            print(f"❌ Error loading database: {e}")
            return False
    
    def _save_database(self):
        """Save channel database to file"""
        try:
            # Update metadata
            self.channels_db['metadata']['updated_at'] = datetime.now().isoformat()
            self.channels_db['metadata']['total_channels'] = len(self.channels_db['channels'])
            self.channels_db['metadata']['countries_with_channels'] = list(self.channels_db['country_channels'].keys())
            
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.channels_db, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Database saved: {self.channels_db['metadata']['total_channels']} channels")
            return True
            
        except Exception as e:
            print(f"❌ Error saving database: {e}")
            return False
    
    async def get_channel_name(self, channel_id):
        """Get channel name, using cache first then API"""
        channel_id = int(channel_id)
        
        # Check cache first
        if str(channel_id) in self.channels_db['channels']:
            self.channels_db['metadata']['stats']['cache_hit_rate'] = \
                (self.channels_db['metadata']['stats']['api_requests_saved'] / 
                 max(1, self.channels_db['metadata']['stats']['api_requests_saved'] + 
                     self.channels_db['metadata']['stats']['channels_discovered'])) * 100
            self.channels_db['metadata']['stats']['api_requests_saved'] += 1
            return self.channels_db['channels'][str(channel_id)]['name']
        
        # Fetch from API
        try:
            match_obj = Match(self.api, 0)
            channel_info = await match_obj.get_channel(channel_id)
            
            if isinstance(channel_info, str):
                channel_name = channel_info
            elif isinstance(channel_info, dict):
                channel_name = channel_info.get('name', f'Channel {channel_id}')
            else:
                channel_name = f'Channel {channel_id}'
            
            # Cache the result
            self.channels_db['channels'][str(channel_id)] = {
                'id': channel_id,
                'name': channel_name,
                'countries': [],
                'first_seen': datetime.now().isoformat()
            }
            
            self.channels_db['metadata']['stats']['channels_discovered'] += 1
            
            print(f"📺 Discovered: {channel_name} ({channel_id})")
            return channel_name
            
        except Exception as e:
            print(f"⚠️ Failed to get channel {channel_id}: {e}")
            return f'Channel {channel_id}'
    
    async def process_live_events(self, limit=30):
        """Process live events to build channel database"""
        try:
            match_obj = Match(self.api, 0)
            live_games_data = await match_obj.live_games()
            
            live_games = live_games_data.get('events', [])
            games_to_process = live_games[:limit] if len(live_games) > limit else live_games
            
            print(f"🔍 Processing {len(games_to_process)} live matches...")
            
            if not self.channels_db['metadata']['created_at']:
                self.channels_db['metadata']['created_at'] = datetime.now().isoformat()
            
            for i, game in enumerate(games_to_process, 1):
                try:
                    match_id = game.get('id')
                    if not match_id:
                        continue
                    
                    home_team = game.get('homeTeam', {}).get('name', 'Unknown')
                    away_team = game.get('awayTeam', {}).get('name', 'Unknown')
                    print(f"[{i}/{len(games_to_process)}] {home_team} vs {away_team}")
                    
                    match = Match(self.api, match_id)
                    channels_data = await match.match_channels()
                    
                    if isinstance(channels_data, dict) and 'countryChannels' in channels_data:
                        await self._process_match_channels(channels_data['countryChannels'])
                    
                    self.channels_db['metadata']['stats']['matches_processed'] += 1
                    
                except Exception as e:
                    print(f"❌ Error processing match {match_id}: {e}")
                    continue
            
            # Save after processing
            self._save_database()
            self._print_stats()
            
        except Exception as e:
            print(f"❌ Error getting live games: {e}")
    
    async def _process_match_channels(self, country_channels):
        """Process channels from a single match"""
        for country_code, channel_ids in country_channels.items():
            country_code = country_code.upper()
            
            # Initialize country in database
            if country_code not in self.channels_db['country_channels']:
                self.channels_db['country_channels'][country_code] = []
            
            for channel_id in channel_ids:
                channel_id = int(channel_id)
                channel_str = str(channel_id)
                
                # Get channel name (uses cache or API)
                channel_name = await self.get_channel_name(channel_id)
                
                # Update channel's country list
                if channel_str in self.channels_db['channels']:
                    if country_code not in self.channels_db['channels'][channel_str]['countries']:
                        self.channels_db['channels'][channel_str]['countries'].append(country_code)
                
                # Add to country's channel list
                if channel_id not in self.channels_db['country_channels'][country_code]:
                    self.channels_db['country_channels'][country_code].append(channel_id)
    
    def get_channels_for_country(self, country_code):
        """Get all channels for a specific country with names"""
        country_code = country_code.upper()
        
        if country_code not in self.channels_db['country_channels']:
            return []
        
        channels = []
        for channel_id in self.channels_db['country_channels'][country_code]:
            channel_str = str(channel_id)
            if channel_str in self.channels_db['channels']:
                channel_info = self.channels_db['channels'][channel_str].copy()
                # Add country info
                channel_info['country_name'] = self.countries.get(country_code, {}).get('name', country_code)
                channels.append(channel_info)
        
        return channels
    
    def search_channels(self, query):
        """Search channels by name"""
        results = []
        query = query.lower()
        
        for channel_id, channel_info in self.channels_db['channels'].items():
            if query in channel_info['name'].lower():
                result = channel_info.copy()
                # Add country names
                result['country_names'] = [
                    self.countries.get(cc, {}).get('name', cc) 
                    for cc in channel_info['countries']
                ]
                results.append(result)
        
        return results
    
    def _print_stats(self):
        """Print database statistics"""
        stats = self.channels_db['metadata']['stats']
        
        print("\n" + "="*60)
        print("📊 CHANNEL DATABASE STATISTICS")
        print("="*60)
        print(f"🎯 Total unique channels: {self.channels_db['metadata']['total_channels']}")
        print(f"🌍 Countries with channels: {len(self.channels_db['country_channels'])}")
        print(f"⚽ Matches processed: {stats['matches_processed']}")
        print(f"📡 New channels discovered: {stats['channels_discovered']}")
        print(f"💾 API requests saved: {stats['api_requests_saved']}")
        if stats['api_requests_saved'] > 0:
            print(f"📈 Cache hit rate: {stats['cache_hit_rate']:.1f}%")
        
        # Top countries by channel count
        country_counts = [(country, len(channels)) for country, channels in self.channels_db['country_channels'].items()]
        country_counts.sort(key=lambda x: x[1], reverse=True)
        
        print(f"\n🏆 Top countries by channel count:")
        for country_code, count in country_counts[:10]:
            country_name = self.countries.get(country_code, {}).get('name', country_code)
            print(f"   {country_name} ({country_code}): {count} channels")


async def main():
    db = ChannelDatabase()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'build':
            # Build database from live events
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            await db.process_live_events(limit)
            
        elif command == 'stats':
            # Show database statistics
            db._print_stats()
            
        elif command == 'country' and len(sys.argv) > 2:
            # Show channels for specific country
            country_code = sys.argv[2].upper()
            channels = db.get_channels_for_country(country_code)
            
            country_name = db.countries.get(country_code, {}).get('name', country_code)
            print(f"\n📺 TV Channels in {country_name} ({country_code}):")
            print("="*50)
            
            if channels:
                for channel in channels:
                    print(f"  {channel['name']} ({channel['id']})")
                    print(f"    Available in: {', '.join([db.countries.get(cc, {}).get('name', cc) for cc in channel['countries']])}")
                    print()
            else:
                print(f"  No channels found for {country_name}")
                
        elif command == 'search' and len(sys.argv) > 2:
            # Search channels by name
            query = ' '.join(sys.argv[2:])
            results = db.search_channels(query)
            
            print(f"\n🔍 Search results for '{query}':")
            print("="*50)
            
            if results:
                for channel in results:
                    print(f"📺 {channel['name']} ({channel['id']})")
                    if channel['country_names']:
                        print(f"   Available in: {', '.join(channel['country_names'])}")
                    print()
            else:
                print(f"  No channels found matching '{query}'")
                
        else:
            print_help()
    else:
        print_help()


def print_help():
    print("📺 TV Channel Database Manager")
    print("=" * 40)
    print("Commands:")
    print("  build [limit]       # Build database from live events (default: 30)")
    print("  stats               # Show database statistics")
    print("  country <code>      # Show channels for country (e.g., US, BR, PT)")
    print("  search <query>      # Search channels by name")
    print("")
    print("Examples:")
    print("  python channel_database.py build 50")
    print("  python channel_database.py stats")
    print("  python channel_database.py country US")
    print("  python channel_database.py search ESPN")


if __name__ == '__main__':
    asyncio.run(main())