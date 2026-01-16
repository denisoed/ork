"""
Secret management utilities for deployment credentials.

This module provides secure access to deployment tokens and credentials
stored in environment variables.
"""

import os
from typing import Dict, List, Optional


class SecretManager:
    """
    Manages deployment secrets and credentials.
    
    Provides secure access to API tokens for Supabase, Vercel,
    and other deployment platforms.
    """
    
    # Required environment variables for different platforms
    SUPABASE_REQUIRED = ['SUPABASE_ACCESS_TOKEN']
    SUPABASE_OPTIONAL = ['SUPABASE_PROJECT_REF', 'SUPABASE_DB_PASSWORD']
    
    VERCEL_REQUIRED = ['VERCEL_TOKEN']
    VERCEL_OPTIONAL = ['VERCEL_ORG_ID', 'VERCEL_PROJECT_ID']
    
    @staticmethod
    def get_supabase_token() -> Optional[str]:
        """
        Get Supabase access token from environment.
        
        Returns:
            Supabase access token or None if not set
        """
        return os.getenv('SUPABASE_ACCESS_TOKEN')
    
    @staticmethod
    def get_supabase_project_ref() -> Optional[str]:
        """
        Get Supabase project reference from environment.
        
        Returns:
            Supabase project reference or None if not set
        """
        return os.getenv('SUPABASE_PROJECT_REF')
    
    @staticmethod
    def get_supabase_db_password() -> Optional[str]:
        """
        Get Supabase database password from environment.
        
        Returns:
            Supabase database password or None if not set
        """
        return os.getenv('SUPABASE_DB_PASSWORD')
    
    @staticmethod
    def get_vercel_token() -> Optional[str]:
        """
        Get Vercel deployment token from environment.
        
        Returns:
            Vercel token or None if not set
        """
        return os.getenv('VERCEL_TOKEN')
    
    @staticmethod
    def get_vercel_org_id() -> Optional[str]:
        """
        Get Vercel organization ID from environment.
        
        Returns:
            Vercel org ID or None if not set
        """
        return os.getenv('VERCEL_ORG_ID')
    
    @staticmethod
    def get_vercel_project_id() -> Optional[str]:
        """
        Get Vercel project ID from environment.
        
        Returns:
            Vercel project ID or None if not set
        """
        return os.getenv('VERCEL_PROJECT_ID')
    
    @classmethod
    def validate_supabase_credentials(cls) -> Dict[str, any]:
        """
        Validate Supabase deployment credentials.
        
        Returns:
            Dict with 'valid' (bool), 'missing' (list), 'available' (list)
        """
        missing = []
        available = []
        
        for var in cls.SUPABASE_REQUIRED:
            if os.getenv(var):
                available.append(var)
            else:
                missing.append(var)
        
        for var in cls.SUPABASE_OPTIONAL:
            if os.getenv(var):
                available.append(var)
        
        return {
            'valid': len(missing) == 0,
            'missing': missing,
            'available': available
        }
    
    @classmethod
    def validate_vercel_credentials(cls) -> Dict[str, any]:
        """
        Validate Vercel deployment credentials.
        
        Returns:
            Dict with 'valid' (bool), 'missing' (list), 'available' (list)
        """
        missing = []
        available = []
        
        for var in cls.VERCEL_REQUIRED:
            if os.getenv(var):
                available.append(var)
            else:
                missing.append(var)
        
        for var in cls.VERCEL_OPTIONAL:
            if os.getenv(var):
                available.append(var)
        
        return {
            'valid': len(missing) == 0,
            'missing': missing,
            'available': available
        }
    
    @classmethod
    def validate_deploy_credentials(cls) -> Dict[str, any]:
        """
        Validate all deployment credentials.
        
        Returns:
            Dict with validation results for each platform
        """
        supabase = cls.validate_supabase_credentials()
        vercel = cls.validate_vercel_credentials()
        
        all_missing = supabase['missing'] + vercel['missing']
        
        return {
            'valid': supabase['valid'] and vercel['valid'],
            'supabase': supabase,
            'vercel': vercel,
            'missing': all_missing
        }
    
    @classmethod
    def get_deployment_env(cls) -> Dict[str, str]:
        """
        Get all deployment-related environment variables as a dict.
        
        Returns:
            Dict of environment variables for deployment commands
        """
        env = {}
        
        # Supabase
        if cls.get_supabase_token():
            env['SUPABASE_ACCESS_TOKEN'] = cls.get_supabase_token()
        if cls.get_supabase_project_ref():
            env['SUPABASE_PROJECT_REF'] = cls.get_supabase_project_ref()
        if cls.get_supabase_db_password():
            env['SUPABASE_DB_PASSWORD'] = cls.get_supabase_db_password()
        
        # Vercel
        if cls.get_vercel_token():
            env['VERCEL_TOKEN'] = cls.get_vercel_token()
        if cls.get_vercel_org_id():
            env['VERCEL_ORG_ID'] = cls.get_vercel_org_id()
        if cls.get_vercel_project_id():
            env['VERCEL_PROJECT_ID'] = cls.get_vercel_project_id()
        
        return env

