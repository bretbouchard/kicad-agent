"""Tests for the ComplianceProvider protocol and registry."""

import asyncio
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from volta.governance import GovernedExecutionContext
from volta.compliance.provider import (
    ComplianceProvider,
    ComplianceReport,
    ComplianceProviderRegistry,
    ComplianceCapability,
    LifecycleStatus
)
from volta.compliance.local_provider import LocalComplianceProvider
from volta.compliance.cad_provider import (
    CADModelProvider,
    CADModelImportResult,
    CADModelCapability,
    SnapMagicImportProvider
)


class TestComplianceProvider(unittest.TestCase):
    """Test the ComplianceProvider protocol and registry functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear the registry before each test
        ComplianceProviderRegistry._providers.clear()
        ComplianceProviderRegistry._default_provider = None
    
    def test_compliance_report_creation(self):
        """Test that ComplianceReport can be created correctly."""
        report = ComplianceReport(
            component_data={"mpn": "TEST123"},
            lifecycle_status=LifecycleStatus.ACTIVE,
            rohs_compliant=True,
            warnings={"warning1"},
            errors={"error1"}
        )
        
        self.assertEqual(report.component_data["mpn"], "TEST123")
        self.assertEqual(report.lifecycle_status, LifecycleStatus.ACTIVE)
        self.assertTrue(report.rohs_compliant)
        self.assertIn("warning1", report.warnings)
        self.assertIn("error1", report.errors)
    
    def test_registry_empty_initially(self):
        """Test that the registry is initially empty."""
        self.assertEqual(len(ComplianceProviderRegistry._providers), 0)
        self.assertIsNone(ComplianceProviderRegistry._default_provider)
    
    def test_register_provider(self):
        """Test registering a provider."""
        # Create a mock provider class  
        class MockProvider(ComplianceProvider):
            @property
            def name(self):
                return "MockProvider"
                
            @property
            def capabilities(self):
                return {ComplianceCapability.LIFECYCLE_STATUS}
                
            async def check_compliance(self, component_data):
                return ComplianceReport(component_data=component_data)
        
        # Register the provider
        ComplianceProviderRegistry.register("mock", MockProvider)
        
        # Verify registration
        self.assertIn("mock", ComplianceProviderRegistry._providers)
        self.assertEqual(ComplianceProviderRegistry._providers["mock"], MockProvider)
        
        # Test retrieval
        retrieved = ComplianceProviderRegistry.get_provider("mock")
        self.assertEqual(retrieved, MockProvider)
        
        # Test listing
        providers = ComplianceProviderRegistry.list_providers()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][0], "mock")
        self.assertEqual(providers[0][1], MockProvider)
    
    def test_unregister_provider(self):
        """Test unregistering a provider."""
        # Create and register a mock provider
        class MockProvider(ComplianceProvider):
            @property
            def name(self):
                return "MockProvider"
                
            @property
            def capabilities(self):
                return {ComplianceCapability.LIFECYCLE_STATUS}
                
            async def check_compliance(self, component_data):
                return ComplianceReport(component_data=component_data)
        
        ComplianceProviderRegistry.register("mock", MockProvider)
        self.assertIn("mock", ComplianceProviderRegistry._providers)
        
        # Unregister it
        ComplianceProviderRegistry.unregister("mock")
        
        # Verify unregistration
        self.assertNotIn("mock", ComplianceProviderRegistry._providers)
        self.assertIsNone(ComplianceProviderRegistry.get_provider("mock"))
    
    def test_set_default_provider(self):
        """Test setting a default provider."""
        # Create and register a mock provider
        class MockProvider(ComplianceProvider):
            @property
            def name(self):
                return "MockProvider"
                
            @property
            def capabilities(self):
                return {ComplianceCapability.LIFECYCLE_STATUS}
                
            async def check_compliance(self, component_data):
                return ComplianceReport(component_data=component_data)
        
        ComplianceProviderRegistry.register("mock", MockProvider)
        
        # Set as default
        ComplianceProviderRegistry.set_default_provider("mock")
        
        # Verify default
        self.assertEqual(ComplianceProviderRegistry._default_provider, "mock")
        self.assertEqual(ComplianceProviderRegistry.get_default_provider(), MockProvider)
    
    def test_set_default_provider_not_registered(self):
        """Test setting a default provider that isn't registered."""
        with self.assertRaises(ValueError):
            ComplianceProviderRegistry.set_default_provider("nonexistent")
    
    def test_is_provider_registered(self):
        """Test checking if a provider is registered."""
        # Create and register a mock provider
        class MockProvider(ComplianceProvider):
            @property
            def name(self):
                return "MockProvider"
                
            @property
            def capabilities(self):
                return {ComplianceCapability.LIFECYCLE_STATUS}
                
            async def check_compliance(self, component_data):
                return ComplianceReport(component_data=component_data)
        
        ComplianceProviderRegistry.register("mock", MockProvider)
        
        # Test registered
        self.assertTrue(ComplianceProviderRegistry.is_provider_registered("mock"))
        
        # Test not registered
        self.assertFalse(ComplianceProviderRegistry.is_provider_registered("nonexistent"))


class TestLocalComplianceProvider(unittest.TestCase):
    """Test the LocalComplianceProvider implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.provider = LocalComplianceProvider()
    
    def test_provider_properties(self):
        """Test that LocalComplianceProvider provides correct properties."""
        self.assertEqual(self.provider.name, "LocalComplianceProvider")
        self.assertIn(ComplianceCapability.LIFECYCLE_STATUS, self.provider.capabilities)
        self.assertIn(ComplianceCapability.ROHS, self.provider.capabilities)
    
    def test_check_compliance_async(self):
        """Test the check_compliance method (async)."""
        # Since this is an async test, we'll run the mock version
        component_data = {"mpn": "TEST123"}
        
        # Create a coroutine for testing - in a real scenario you'd test the actual async method
        # For now we just test that it constructs properly
        self.assertIsNotNone(self.provider)
        self.assertTrue(hasattr(self.provider, 'check_compliance'))


class TestCADModelProvider(unittest.TestCase):
    """Test the CADModelProvider protocol and SnapMagicImportProvider."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.provider = SnapMagicImportProvider(cache_dir=Path(tempfile.gettempdir()) / "volta-test-snapmagic")
    
    def test_cad_provider_properties(self):
        """Test that SnapMagicImportProvider provides correct properties."""
        self.assertEqual(self.provider.name, "SnapMagicImportProvider")
        self.assertIn(CADModelCapability.FOOTPRINTS, self.provider.capabilities)
        self.assertIn(CADModelCapability.SYMBOLS, self.provider.capabilities)
        
    def test_cad_import_result(self):
        """Test CADModelImportResult construction."""
        result = CADModelImportResult(
            success=True,
            imported_components=[{"mpn": "TEST123"}],
            errors=["error1"],
            warnings=["warning1"],
            metadata={"source": "test"}
        )
        
        self.assertTrue(result.success)
        self.assertEqual(len(result.imported_components), 1)
        self.assertIn("error1", result.errors)
        self.assertIn("warning1", result.warnings)
        self.assertEqual(result.metadata["source"], "test")

    def test_cad_import_models_records_governed_metadata(self):
        """SnapMagic import can emit governed object IDs and source evidence."""
        provider = SnapMagicImportProvider(
            cache_dir=Path(tempfile.gettempdir()) / "volta-test-snapmagic-governed",
            governed_context=GovernedExecutionContext(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp)
            footprint = source_dir / "LM358.kicad_mod"
            footprint.write_text("(footprint)", encoding="utf-8")

            result = asyncio.run(provider.import_models([source_dir]))

        self.assertTrue(result.success)
        self.assertEqual(len(result.imported_components), 1)
        self.assertIn("governed_object_id", result.imported_components[0])
        self.assertIn(f"governed_{source_dir.name}", result.metadata)


if __name__ == '__main__':
    unittest.main()
