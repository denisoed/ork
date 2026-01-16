"""
User Notification System - notifies user about completion with links to spec-feature files.
"""

import os
from typing import Dict, Any, Optional
from orchestrator.tools.spec_feature_tools import check_spec_structure

def notify_user(state: SharedState) -> None:
    """
    Notify user about completion with links to spec-feature files.
    
    Args:
        state: Current shared state
    """
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    validation_report = state.get('final_validation_report', {})
    
    print("\n" + "=" * 70)
    print("WORK COMPLETED")
    print("=" * 70)
    
    if feature_name:
        print(f"\nFeature: {feature_name}")
        
        # Check which spec files exist
        spec_files = check_spec_structure(feature_name, spec_path)
        
        print("\nSpecification Files:")
        spec_base_path = os.path.join(spec_path, "features", feature_name)
        
        if spec_files.get('spec'):
            print(f"  - Specification: {os.path.join(spec_base_path, 'spec.md')}")
        if spec_files.get('plan'):
            print(f"  - Plan: {os.path.join(spec_base_path, 'plan.md')}")
        if spec_files.get('tasks'):
            print(f"  - Tasks: {os.path.join(spec_base_path, 'tasks.md')}")
        if spec_files.get('verify-report'):
            print(f"  - Verify Report: {os.path.join(spec_base_path, 'verify-report.md')}")
        if spec_files.get('clarifications'):
            print(f"  - Clarifications: {os.path.join(spec_base_path, 'clarifications.md')}")
        
        print(f"\nView in browser: npx spec-feature view {feature_name}")
    
    # Print validation results
    if validation_report:
        status = validation_report.get('status', 'unknown')
        print(f"\nValidation Status: {status.upper()}")
        
        if status == 'passed':
            print("✓ All checks passed!")
        else:
            print("✗ Some issues found")
            issues = validation_report.get('issues', [])
            if issues:
                print("\nIssues:")
                for issue in issues[:5]:  # Show first 5 issues
                    print(f"  - {issue}")
                if len(issues) > 5:
                    print(f"  ... and {len(issues) - 5} more")
        
        summary = validation_report.get('summary', '')
        if summary:
            print(f"\nSummary: {summary}")
        
        # Test results
        test_results = validation_report.get('test_results', {})
        if test_results.get('ran'):
            test_status = "PASSED" if test_results.get('passed') else "FAILED"
            print(f"\nTests: {test_status}")
    
    print("\n" + "=" * 70)
    print()

def get_notification_summary(state: SharedState) -> Dict[str, Any]:
    """
    Get notification summary for programmatic use.
    
    Args:
        state: Current shared state
        
    Returns:
        Dictionary with notification summary
    """
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    validation_report = state.get('final_validation_report', {})
    
    summary = {
        "feature_name": feature_name,
        "status": validation_report.get('status', 'unknown'),
        "spec_files": {}
    }
    
    if feature_name:
        spec_files = check_spec_structure(feature_name, spec_path)
        spec_base_path = os.path.join(spec_path, "features", feature_name)
        
        for file_type, exists in spec_files.items():
            if exists:
                summary["spec_files"][file_type] = os.path.join(spec_base_path, f"{file_type}.md" if file_type != 'spec' else 'spec.md')
    
    summary["validation"] = validation_report
    
    return summary
