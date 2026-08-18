"""Tests for the RoutingProvider protocol and registry."""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from volta.routing.provider import (
    RoutingProvider,
    RoutingProviderInfo,
    RoutingProviderRegistry,
    RoutingProviderType,
    RoutingProviderError,
)
from volta.routing.freerouting_provider import FreeroutingProvider
from volta.routing.constraints import RoutingConstraints
from volta.routing.graph import RoutingGraph
from volta.routing.pathfinder import RouteResult, RouteFailure


class TestRoutingProvider(unittest.TestCase):
    """Test the RoutingProvider protocol and registry functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear the registry before each test
        RoutingProviderRegistry._providers.clear()
        RoutingProviderRegistry._default_provider = None
    
    def test_provider_info_creation(self):
        """Test that RoutingProviderInfo can be created correctly."""
        info = RoutingProviderInfo(
            name="TestProvider",
            type=RoutingProviderType.A_STAR,
            version="1.0.0",
            description="A test provider"
        )
        
        self.assertEqual(info.name, "TestProvider")
        self.assertEqual(info.type, RoutingProviderType.A_STAR)
        self.assertEqual(info.version, "1.0.0")
        self.assertEqual(info.description, "A test provider")
    
    def test_registry_empty_initially(self):
        """Test that the registry is initially empty."""
        self.assertEqual(len(RoutingProviderRegistry._providers), 0)
        self.assertIsNone(RoutingProviderRegistry._default_provider)
    
    def test_register_provider(self):
        """Test registering a provider."""
        # Create a mock provider class
        class MockProvider(RoutingProvider):
            @property
            def info(self):
                return RoutingProviderInfo(
                    name="MockProvider",
                    type=RoutingProviderType.CUSTOM,
                    version="1.0.0",
                    description="Mock provider"
                )
                
            def can_route(self, constraints):
                return True
                
            def route_net(self, graph, net_name, constraints, **kwargs):
                return RouteResult("test", True, [], 0.0)
                
            def route_all_nets(self, graph, net_names, constraints, **kwargs):
                return {"test": RouteResult("test", True, [], 0.0)}
        
        # Register the provider
        RoutingProviderRegistry.register("mock", MockProvider)
        
        # Verify registration
        self.assertIn("mock", RoutingProviderRegistry._providers)
        self.assertEqual(RoutingProviderRegistry._providers["mock"], MockProvider)
        
        # Test retrieval
        retrieved = RoutingProviderRegistry.get_provider("mock")
        self.assertEqual(retrieved, MockProvider)
        
        # Test listing
        providers = RoutingProviderRegistry.list_providers()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "MockProvider")
    
    def test_unregister_provider(self):
        """Test unregistering a provider."""
        # Create and register a mock provider
        class MockProvider(RoutingProvider):
            @property
            def info(self):
                return RoutingProviderInfo(
                    name="MockProvider",
                    type=RoutingProviderType.CUSTOM,
                    version="1.0.0",
                    description="Mock provider"
                )
                
            def can_route(self, constraints):
                return True
                
            def route_net(self, graph, net_name, constraints, **kwargs):
                return RouteResult("test", True, [], 0.0)
                
            def route_all_nets(self, graph, net_names, constraints, **kwargs):
                return {"test": RouteResult("test", True, [], 0.0)}
        
        RoutingProviderRegistry.register("mock", MockProvider)
        self.assertIn("mock", RoutingProviderRegistry._providers)
        
        # Unregister it
        RoutingProviderRegistry.unregister("mock")
        
        # Verify unregistration
        self.assertNotIn("mock", RoutingProviderRegistry._providers)
        self.assertIsNone(RoutingProviderRegistry.get_provider("mock"))
    
    def test_set_default_provider(self):
        """Test setting a default provider."""
        # Create and register a mock provider
        class MockProvider(RoutingProvider):
            @property
            def info(self):
                return RoutingProviderInfo(
                    name="MockProvider",
                    type=RoutingProviderType.CUSTOM,
                    version="1.0.0",
                    description="Mock provider"
                )
                
            def can_route(self, constraints):
                return True
                
            def route_net(self, graph, net_name, constraints, **kwargs):
                return RouteResult("test", True, [], 0.0)
                
            def route_all_nets(self, graph, net_names, constraints, **kwargs):
                return {"test": RouteResult("test", True, [], 0.0)}
        
        RoutingProviderRegistry.register("mock", MockProvider)
        
        # Set as default
        RoutingProviderRegistry.set_default_provider("mock")
        
        # Verify default
        self.assertEqual(RoutingProviderRegistry._default_provider, "mock")
        self.assertEqual(RoutingProviderRegistry.get_default_provider(), MockProvider)
    
    def test_set_default_provider_not_registered(self):
        """Test setting a default provider that isn't registered."""
        with self.assertRaises(ValueError):
            RoutingProviderRegistry.set_default_provider("nonexistent")
    
    def test_create_provider_instance(self):
        """Test creating an instance of a registered provider."""
        # Create and register a mock provider
        class MockProvider(RoutingProvider):
            def __init__(self, **kwargs):
                self._kwargs = kwargs
                super().__init__()
                
            @property
            def info(self):
                return RoutingProviderInfo(
                    name="MockProvider",
                    type=RoutingProviderType.CUSTOM,
                    version="1.0.0",
                    description="Mock provider"
                )
                
            def can_route(self, constraints):
                return True
                
            def route_net(self, graph, net_name, constraints, **kwargs):
                return RouteResult("test", True, [], 0.0)
                
            def route_all_nets(self, graph, net_names, constraints, **kwargs):
                return {"test": RouteResult("test", True, [], 0.0)}
        
        RoutingProviderRegistry.register("mock", MockProvider)
        
        # Create instance with arguments
        provider = RoutingProviderRegistry.create_provider("mock", test_arg="value")
        self.assertIsInstance(provider, MockProvider)
        # Note: We can't easily verify kwargs without more complex mocking
    
    def test_create_provider_not_registered(self):
        """Test creating an instance of a provider that isn't registered."""
        with self.assertRaises(ValueError):
            RoutingProviderRegistry.create_provider("nonexistent")


class TestFreeroutingProvider(unittest.TestCase):
    """Test the FreeroutingProvider implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.provider = FreeroutingProvider()
        
    def test_provider_info(self):
        """Test that FreeroutingProvider provides correct info."""
        info = self.provider.info
        self.assertEqual(info.name, "FreeroutingProvider")
        self.assertEqual(info.type, RoutingProviderType.FREEROUTING)
        self.assertEqual(info.version, "1.0.0")
        self.assertEqual(info.description, "Freerouting integration for production-quality auto-routing")
        
    @patch('volta.routing.freerouting_provider.is_freerouting_available')
    def test_can_route(self, mock_available):
        """Test the can_route method."""
        # Test with Freerouting available
        mock_available.return_value = True
        provider = FreeroutingProvider()
        constraints = RoutingConstraints()
        can_route = provider.can_route(constraints)
        self.assertTrue(can_route)
        
        # Test with Freerouting not available
        mock_available.return_value = False
        provider = FreeroutingProvider()
        can_route = provider.can_route(constraints)
        self.assertFalse(can_route)
        
    def test_route_net(self):
        """Test the route_net method."""
        # Create mocks for required components
        constraints = RoutingConstraints()
        graph = MagicMock(spec=RoutingGraph)
        
        # This would be more elaborate to fully test but the basic structure should work
        result = self.provider.route_net(graph, "test_net", constraints)
        # Result depends on availability, but should be either RouteResult or RouteFailure
        
    def test_route_all_nets(self):
        """Test the route_all_nets method."""
        # Create mocks for required components
        constraints = RoutingConstraints()
        graph = MagicMock(spec=RoutingGraph)
        
        # This would be more elaborate to fully test but the basic structure should work
        results = self.provider.route_all_nets(graph, ["net1", "net2"], constraints)
        self.assertIsInstance(results, dict)
        self.assertIn("net1", results)
        self.assertIn("net2", results)


if __name__ == '__main__':
    unittest.main()