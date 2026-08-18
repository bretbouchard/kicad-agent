#!/usr/bin/env python3
"""Demo script showing how to use the RoutingProvider system."""

import sys
import os
from pathlib import Path

# Add the src directory to the Python path so we can import volta modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from volta.routing.provider import (
    RoutingProviderRegistry,
    RoutingProviderType,
    RoutingProviderInfo
)
from volta.routing.freerouting_provider import FreeroutingProvider


def main():
    """Demonstrate the RoutingProvider system usage."""
    print("=== RoutingProvider System Demo ===\n")
    
    # Show initial registry state
    print("1. Initial registry state:")
    providers = RoutingProviderRegistry.list_providers()
    print(f"   Registered providers: {len(providers)}")
    
    # Register the Freerouting provider
    print("\n2. Registering FreeroutingProvider...")
    RoutingProviderRegistry.register("freerouting", FreeroutingProvider)
    print("   FreeroutingProvider registered successfully")
    
    # List available providers
    print("\n3. Available providers:")
    providers = RoutingProviderRegistry.list_providers()
    for provider_info in providers:
        print(f"   - {provider_info.name} ({provider_info.type.value}) v{provider_info.version}: {provider_info.description}")
    
    # Create a provider instance
    print("\n4. Creating a FreeroutingProvider instance...")
    try:
        provider = RoutingProviderRegistry.create_provider("freerouting")
        print(f"   Created {provider.info.name} successfully!")
        print(f"   Status: {'Available' if provider.info.available else 'Not available'}")
    except Exception as e:
        print(f"   Failed to create provider: {e}")
    
    # Test the registry functionality
    print("\n5. Registry functionality test:")
    print(f"   Provider 'freerouting' registered: {RoutingProviderRegistry.is_provider_registered('freerouting')}")
    print(f"   Provider 'nonexistent' registered: {RoutingProviderRegistry.is_provider_registered('nonexistent')}")
    
    # Set default provider
    print("\n6. Setting default provider...")
    try:
        RoutingProviderRegistry.set_default_provider("freerouting")
        default_provider = RoutingProviderRegistry.get_default_provider()
        if default_provider:
            print(f"   Default provider set to: {default_provider.__name__}")
        else:
            print("   No default provider set")
    except Exception as e:
        print(f"   Failed to set default provider: {e}")
    
    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    main()