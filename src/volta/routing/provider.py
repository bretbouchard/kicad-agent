"""Routing provider protocol and registry for KiCad routing engines.

This module defines the RoutingProvider protocol that enables different routing
engines to be plugged into the routing system. The registry allows for
dynamic discovery and selection of routing providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Type, Union

from volta.routing.constraints import RoutingConstraints
from volta.routing.graph import RoutingGraph
from volta.routing.pathfinder import RouteResult, RouteFailure


class RoutingProviderError(Exception):
    """Base exception for routing provider errors."""


class RoutingProviderType(Enum):
    """Enumeration of routing provider types."""
    A_STAR = "a_star"
    FREEROUTING = "freerouting"
    AUTOROUTER = "autorouter"
    CUSTOM = "custom"


@dataclass(frozen=True)
class RoutingProviderInfo:
    """Information about a routing provider."""
    
    name: str
    type: RoutingProviderType
    version: str
    description: str
    available: bool = True


class RoutingProvider(Protocol):
    """Protocol defining the interface for routing providers.
    
    This protocol allows different routing engines to be used interchangeably.
    All providers must implement these methods to be compatible with the routing system.
    """
    
    @property
    @abstractmethod
    def info(self) -> RoutingProviderInfo:
        """Get information about the routing provider."""
        ...
        
    @abstractmethod
    def can_route(self, constraints: RoutingConstraints) -> bool:
        """Check if this provider can handle the given routing constraints.
        
        Args:
            constraints: Routing constraints to check
            
        Returns:
            True if this provider can handle the constraints, False otherwise
        """
        ...
        
    @abstractmethod
    def route_net(
        self,
        graph: RoutingGraph,
        net_name: str,
        constraints: RoutingConstraints,
        **kwargs: Any
    ) -> Union[RouteResult, RouteFailure]:
        """Route a single net using this provider.
        
        Args:
            graph: Routing graph to use for routing
            net_name: Name of the net to route
            constraints: Routing constraints to apply
            **kwargs: Additional provider-specific parameters
            
        Returns:
            RouteResult on success, RouteFailure on failure
        """
        ...

    @abstractmethod
    def route_all_nets(
        self,
        graph: RoutingGraph,
        net_names: List[str],
        constraints: RoutingConstraints,
        **kwargs: Any
    ) -> Dict[str, Union[RouteResult, RouteFailure]]:
        """Route all nets using this provider.
        
        Args:
            graph: Routing graph to use for routing
            net_names: Names of nets to route
            constraints: Routing constraints to apply
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary mapping net names to RouteResult or RouteFailure objects
        """
        ...


class RoutingProviderRegistry:
    """Registry for routing providers.
    
    Maintains a collection of available routing providers that can be dynamically
    discovered and selected at runtime.
    """
    
    _providers: Dict[str, Type[RoutingProvider]] = {}
    _default_provider: Optional[str] = None
    
    @classmethod
    def register(cls, provider_type: str, provider_class: Type[RoutingProvider]) -> None:
        """Register a routing provider.
        
        Args:
            provider_type: Unique identifier for the provider
            provider_class: Class implementing the RoutingProvider protocol
        """
        cls._providers[provider_type] = provider_class
        
    @classmethod
    def unregister(cls, provider_type: str) -> None:
        """Unregister a routing provider.
        
        Args:
            provider_type: Unique identifier for the provider to remove
        """
        if provider_type in cls._providers:
            del cls._providers[provider_type]
            
    @classmethod
    def get_provider(cls, provider_type: str) -> Optional[Type[RoutingProvider]]:
        """Get a registered provider class by type.
        
        Args:
            provider_type: Provider type identifier
            
        Returns:
            Provider class or None if not found
        """
        return cls._providers.get(provider_type)
        
    @classmethod
    def list_providers(cls) -> List[RoutingProviderInfo]:
        """List all registered providers.
        
        Returns:
            List of RoutingProviderInfo objects for all registered providers
        """
        providers: list[RoutingProviderInfo] = []
        for provider_cls in cls._providers.values():
            info_attr = getattr(provider_cls, "info", None)
            if isinstance(info_attr, property):
                provider = provider_cls()
                providers.append(provider.info)
            else:
                providers.append(info_attr)
        return providers
        
    @classmethod
    def set_default_provider(cls, provider_type: str) -> None:
        """Set the default routing provider.
        
        Args:
            provider_type: Provider type identifier to set as default
            
        Raises:
            ValueError: If the provider type is not registered
        """
        if provider_type not in cls._providers:
            raise ValueError(f"Provider '{provider_type}' is not registered")
        cls._default_provider = provider_type
        
    @classmethod
    def get_default_provider(cls) -> Optional[Type[RoutingProvider]]:
        """Get the default routing provider.
        
        Returns:
            Default provider class or None if not set
        """
        if cls._default_provider is None:
            return None
        return cls._providers.get(cls._default_provider)
        
    @classmethod
    def create_provider(cls, provider_type: str, **kwargs: Any) -> RoutingProvider:
        """Create an instance of a routing provider.
        
        Args:
            provider_type: Provider type identifier
            **kwargs: Arguments to pass to the provider constructor
            
        Returns:
            Instance of the requested routing provider
            
        Raises:
            ValueError: If the provider type is not registered
        """
        provider_class = cls.get_provider(provider_type)
        if provider_class is None:
            raise ValueError(f"Provider '{provider_type}' is not registered")
        return provider_class(**kwargs)
        
    @classmethod
    def is_provider_registered(cls, provider_type: str) -> bool:
        """Check if a provider type is registered.
        
        Args:
            provider_type: Provider type identifier
            
        Returns:
            True if the provider is registered, False otherwise
        """
        return provider_type in cls._providers
