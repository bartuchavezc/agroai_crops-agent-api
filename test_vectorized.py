#!/usr/bin/env python3
import asyncio
import sys
import os
from datetime import datetime

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.app.weather_data.infrastructure.smn_client import SMNClient

async def test_vectorized_optimization():
    """Prueba la optimización vectorizada del SMNClient"""
    
    print("🧪 TESTING VECTORIZED OPTIMIZATION")
    print("=" * 50)
    
    client = SMNClient()
    
    # Coordenadas de prueba
    test_coordinates = [
        (-34.6118, -58.3960),  # Buenos Aires
        (-31.4201, -64.1888),  # Córdoba  
        (-32.9442, -60.6505),  # Rosario
        (-25.2637, -57.5759),  # Asunción (Paraguay, límite)
        (-26.8083, -65.2176)   # Tucumán
    ]
    
    print(f"📍 Testing with {len(test_coordinates)} coordinates:")
    for i, (lat, lon) in enumerate(test_coordinates):
        print(f"   {i+1}. ({lat:.4f}, {lon:.4f})")
    
    print("\n🚀 Starting batch fetch with vectorized processing...")
    
    start_time = datetime.now()
    
    try:
        # Usar fecha específica que sabemos que tiene datos
        target_date = datetime(2025, 5, 26, 12, 0, 0)  # 26 de mayo 2025, 12:00
        print(f"🗓️  Using target date: {target_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        results = await client.get_forecast_batch(test_coordinates, target_date)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n⏱️  Total execution time: {duration:.2f} seconds")
        print(f"📊 Results obtained: {len([r for r in results if r is not None])}/{len(test_coordinates)} successful")
        
        print("\n🌡️  Temperature results:")
        for i, (result, (lat, lon)) in enumerate(zip(results, test_coordinates)):
            if result:
                temp = result.get('temperature')
                humidity = result.get('humidity')
                
                # Formatear valores seguros para None
                temp_str = f"{temp:.1f}°C" if temp is not None else "N/A"
                humidity_str = f"{humidity:.1f}%" if humidity is not None else "N/A"
                
                print(f"   {i+1}. ({lat:.2f}, {lon:.2f}): {temp_str}, {humidity_str} humidity")
            else:
                print(f"   {i+1}. ({lat:.2f}, {lon:.2f}): ❌ Failed to get data")
        
        print(f"\n✅ Vectorized optimization test completed successfully!")
        
        # Performance analysis
        coords_per_second = len(test_coordinates) / duration if duration > 0 else 0
        print(f"🚀 Performance: {coords_per_second:.1f} coordinates per second")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_vectorized_optimization()) 