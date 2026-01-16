"""
User Notification System - notifies user about completion with links to spec-feature files.
"""

import os
from typing import Dict, Any, Optional
from orchestrator.state import SharedState
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
        
        spec_base_path = os.path.join(spec_path, "features", feature_name)
        
        # Acceptance Package Documents
        print("\n" + "=" * 70)
        print("ACCEPTANCE PACKAGE")
        print("=" * 70)
        
        if spec_files.get('summary'):
            print(f"  ✓ Summary: {os.path.join(spec_base_path, 'summary.md')}")
        if spec_files.get('validation-report'):
            print(f"  ✓ Validation Report: {os.path.join(spec_base_path, 'validation_report.md')}")
        if spec_files.get('trace'):
            print(f"  ✓ Trace (JSON): {os.path.join(spec_base_path, 'trace.json')}")
            # Check if trace.md exists too
            trace_md_path = os.path.join(spec_base_path, 'trace.md')
            if os.path.exists(trace_md_path):
                print(f"  ✓ Trace (Markdown): {trace_md_path}")
        if spec_files.get('risks-debt') or os.path.exists(os.path.join(spec_base_path, 'risks_debt.md')):
            print(f"  ✓ Risks & Debt: {os.path.join(spec_base_path, 'risks_debt.md')}")
        if spec_files.get('verify-report'):
            print(f"  ✓ Verify Report: {os.path.join(spec_base_path, 'verify-report.md')}")
        
        # Specification Files
        print("\nSpecification Files:")
        if spec_files.get('spec'):
            print(f"  - Specification: {os.path.join(spec_base_path, 'spec.md')}")
        if spec_files.get('plan'):
            print(f"  - Plan: {os.path.join(spec_base_path, 'plan.md')}")
        if spec_files.get('tasks'):
            print(f"  - Tasks: {os.path.join(spec_base_path, 'tasks.md')}")
        if spec_files.get('clarifications'):
            print(f"  - Clarifications: {os.path.join(spec_base_path, 'clarifications.md')}")
        
        print(f"\nView in browser: npx spec-feature view {feature_name}")
    
    # Print validation results
    if validation_report:
        status = validation_report.get('status', 'unknown')
        phase = state.get('phase', 'UNKNOWN')
        
        print("\n" + "=" * 70)
        print("VALIDATION & EVIDENCE STATUS")
        print("=" * 70)
        
        print(f"\nPhase: {phase}")
        print(f"Validation Status: {status.upper()}")
        
        # Check evidence completeness from validation report or verify-report
        validation_results = validation_report.get('validation_results', {})
        issues = validation_report.get('issues', [])
        
        # Check if there are evidence-related issues
        evidence_issues = [issue for issue in issues if any(keyword in issue.lower() for keyword in ['evidence', 'trace', 'missing', 'unknown'])]
        
        if evidence_issues:
            print("\n⚠️  Evidence Issues Detected:")
            for issue in evidence_issues[:5]:
                print(f"  - {issue}")
            if len(evidence_issues) > 5:
                print(f"  ... and {len(evidence_issues) - 5} more")
        
        if status == 'passed' and phase == 'DONE':
            print("\n✅ All checks passed and evidence complete!")
            print("✅ Feature marked as DONE")
        elif status == 'passed' and phase != 'DONE':
            print("\n⚠️  Validation passed but phase is not DONE")
            print("   (Evidence completeness check may have failed)")
        else:
            print("\n✗ Some issues found")
            if issues and not evidence_issues:
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
            test_status = "✅ PASSED" if test_results.get('passed') else "❌ FAILED"
            print(f"\nTests: {test_status}")
        
        # Deployment URLs
        deployment_urls = state.get('deployment_urls', {})
        if deployment_urls and any(url for url in deployment_urls.values() if url):
            print("\n" + "=" * 70)
            print("DEPLOYMENT")
            print("=" * 70)
            for deploy_type, url in deployment_urls.items():
                if url:
                    print(f"  - {deploy_type}: {url}")
            
            # Healthcheck status
            healthcheck = validation_results.get('service', {}).get('healthcheck', {})
            if healthcheck.get('checked'):
                hc_status = "✅ passed" if healthcheck.get('passed') else "❌ failed"
                print(f"  - Healthcheck: {hc_status}")
    
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
