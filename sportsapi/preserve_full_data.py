#!/usr/bin/env python3
"""
Data Preservation Strategy for SportAPI Channel Data

This script demonstrates how to preserve both:
1. Full rich SportAPI data (all fields, logos, descriptions, etc.)
2. Optimized structure for tvmap.py performance

Future runs will save both structures automatically.
"""

import json
from datetime import datetime

def create_dual_structure_example():
    """Create example of dual data structure we should preserve"""
    
    # Example of what FULL SportAPI data might look like
    full_data_example = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "source": "SportAPI (sportapi7.p.rapidapi.com)",
            "total_countries": 250,
            "total_channels": 3617,
            "data_completeness": "full",
            "note": "Complete SportAPI response data preserved"
        },
        "channels_by_country": {
            "US": [
                {
                    "id": 672,
                    "name": "ESPN",
                    "country_code": "US",
                    "country_name": "United States",
                    "continent": "North America",
                    "is_eu": False,
                    "logo": "https://example.com/espn-logo.png",
                    "website": "https://espn.com",
                    "description": "Sports network covering live events and analysis",
                    "category": "Sports",
                    "language": ["English"],
                    "hd_available": True,
                    "streaming_provider": "ESPN+",
                    "cable_provider": ["Comcast", "Verizon", "AT&T"],
                    "first_discovered": datetime.now().isoformat()
                }
            ]
        },
        "all_channels": {
            "672": {
                "id": 672,
                "name": "ESPN",
                "countries": ["US", "CA"],  # Available in multiple countries
                "logos": ["https://example.com/espn-logo.png"],
                "websites": ["https://espn.com"],
                "descriptions": ["Sports network covering live events"],
                "categories": ["Sports"],
                "languages": ["English"],
                "features": {
                    "hd": True,
                    "4k": False,
                    "streaming": True,
                    "cable": True
                },
                "providers": {
                    "streaming": ["ESPN+"],
                    "cable": ["Comcast", "Verizon", "AT&T"]
                },
                "first_discovered": datetime.now().isoformat()
            }
        }
    }
    
    # What tvmap.py actually needs (optimized)
    optimized_data_example = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "data_source": "SportAPI (sportapi7.p.rapidapi.com)",
            "total_countries": 250,
            "total_channels": 3617,
            "api_compatibility": "SofaScore 100% compatible",
            "structure": "optimized_for_performance"
        },
        "countries": {
            "US": {
                "name": "United States",
                "continent": "North America",
                "is_eu": False
            }
        },
        "channels": {
            "672": {
                "id": 672,
                "name": "ESPN",
                "countries": ["US", "CA"],
                "logos": ["https://example.com/espn-logo.png"],
                "websites": ["https://espn.com"],
                "first_discovered": datetime.now().isoformat()
            }
        }
    }
    
    # Save example structures
    with open('data/channels_full_example.json', 'w', encoding='utf-8') as f:
        json.dump(full_data_example, f, indent=2, ensure_ascii=False)
    
    with open('data/channels_optimized_example.json', 'w', encoding='utf-8') as f:
        json.dump(optimized_data_example, f, indent=2, ensure_ascii=False)
    
    print("✅ Created example data structures:")
    print("   📁 channels_full_example.json - Complete SportAPI data")
    print("   📁 channels_optimized_example.json - Performance-optimized structure")
    print("\n💡 Future Recommendation:")
    print("   • Modify channel_fetcher.py to save both structures")
    print("   • Keep channels_full.json for rich data")
    print("   • Keep channels_database.json for tvmap.py performance")

if __name__ == "__main__":
    create_dual_structure_example()