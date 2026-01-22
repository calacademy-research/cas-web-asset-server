"""Tests for GenerationStats class."""

import time
import pytest
from pregen.generation_stats import GenerationStats


class TestGenerationStats:
    """Tests for GenerationStats class."""
    
    def test_elapsed_seconds(self):
        """Test elapsed time calculation."""
        stats = GenerationStats()
        stats.start_time = time.time() - 10
        
        assert stats.elapsed_seconds >= 10
        assert stats.elapsed_seconds < 12
    
    def test_rate_per_second(self):
        """Test rate calculation."""
        stats = GenerationStats()
        stats.start_time = time.time() - 10
        stats.processed = 100
        
        rate = stats.rate_per_second
        
        assert rate >= 9
        assert rate <= 11
    
    def test_rate_per_minute(self):
        """Test rate per minute."""
        stats = GenerationStats()
        stats.start_time = time.time() - 60
        stats.processed = 100
        
        rate = stats.rate_per_minute
        
        assert rate >= 90
        assert rate <= 110
    
    def test_estimated_remaining(self):
        """Test estimated remaining time."""
        stats = GenerationStats(total_to_process=200)
        stats.start_time = time.time() - 10
        stats.processed = 100
        
        remaining = stats.estimated_remaining_seconds
        
        assert remaining >= 9
        assert remaining <= 12
    
    def test_completed_count(self):
        """Test completed count."""
        stats = GenerationStats()
        stats.processed = 50
        stats.skipped = 10
        stats.errors = 5
        
        assert stats.completed_count == 65
    
    def test_remaining_count(self):
        """Test remaining count."""
        stats = GenerationStats(total_to_process=100)
        stats.processed = 50
        stats.skipped = 10
        stats.errors = 5
        
        assert stats.remaining_count == 35
