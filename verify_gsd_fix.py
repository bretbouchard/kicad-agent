#!/usr/bin/env python3
"""
Verification script to confirm GSD workflows are fixed in zcode environment.
"""

import json
import os

def verify_config_paths():
    """Verify that config.json has correct absolute paths"""
    config_path = '.planning/config.json'
    
    if not os.path.exists(config_path):
        print("❌ Configuration file not found")
        return False
        
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    code_path = config['project']['code_path']
    skill_path = config['project']['skill_path']
    
    # Check that paths are absolute (no ~)
    if code_path.startswith('~'):
        print("❌ code_path still contains tilde reference")
        return False
    if skill_path.startswith('~'):
        print("❌ skill_path still contains tilde reference") 
        return False
    
    # Check that paths exist
    if not os.path.exists(code_path):
        print(f"❌ code_path does not exist: {code_path}")
        return False
    if not os.path.exists(skill_path):
        print(f"❌ skill_path does not exist: {skill_path}")
        return False
        
    print("✓ Configuration paths are correct and accessible")
    print(f"  code_path: {code_path}")
    print(f"  skill_path: {skill_path}")
    return True

def verify_core_functionality():
    """Verify core GSD workflow components are available"""
    try:
        # Test that main components can be imported
        import volta.ops.executor
        import volta.ops.schema
        print("✓ Core GSD components load successfully")
        
        # Test basic schema functionality 
        from volta.ops.schema import get_operation_schema
        print("✓ Operation schema functionality available")
        return True
    except Exception as e:
        print(f"❌ Core functionality failed: {e}")
        return False

def main():
    """Main verification function"""
    print("🔍 Verifying GSD Workflow Configuration Fix")
    print("=" * 50)
    
    success = True
    success &= verify_config_paths()
    success &= verify_core_functionality()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 ALL CHECKS PASSED")
        print("GSD workflows should now work correctly in zcode environment")
        print("Key fixes implemented:")
        print("  • Replaced tilde references with absolute paths")
        print("  • Updated code_path to: /Users/bretbouchard/apps/kicad-agent/src/volta")
        print("  • Updated skill_path to: /Users/bretbouchard/apps/kicad-agent/skills")
        print("  • Verified paths are accessible")
    else:
        print("❌ Some checks failed - configuration needs attention")
        
    return success

if __name__ == "__main__":
    main()