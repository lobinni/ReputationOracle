"""
Integration tests for ReputationOracle against real StudioNet consensus.

Run with: gltest tests/integration/ -v -s --network studionet
"""

import pytest


@pytest.mark.integration
def test_full_public_surface(deploy_contract, test_account):
    """
    Exercise all write methods and views against live consensus.
    """
    oracle = deploy_contract("contracts/reputation_oracle.py")
    
    # create_profile
    profile_id = oracle.create_profile(
        entity_name="TestEntity",
        url="https://example.com/",
        criteria="Evaluate trustworthiness based on public information",
        min_alert_score=3,
        cooldown_seconds=60,
    )
    assert profile_id is not None
    print(f"Created profile: {profile_id}")
    
    # get_profile
    state = oracle.view().get_profile(profile_id)
    assert state["entity_name"] == "TestEntity"
    assert state["active"] is True
    assert state["reliable"] is True
    print(f"Profile state: score={state['score']}")
    
    # get_sources
    sources = oracle.view().get_sources(profile_id)
    assert len(sources) == 1
    print(f"Sources: {sources}")
    
    # get_signals
    signals = oracle.view().get_signals(profile_id)
    print(f"Signals: {len(signals)} extracted")
    
    # subscribe
    oracle.subscribe(profile_id, alert_below=4)
    subscribers = oracle.view().get_subscribers(profile_id)
    assert len(subscribers) >= 1
    print("Subscribed")
    
    # set_min_alert_score (raise only)
    oracle.set_min_alert_score(profile_id, 4)
    state = oracle.view().get_profile(profile_id)
    assert state["min_alert_score"] == 4
    
    with pytest.raises(Exception, match="may only be raised"):
        oracle.set_min_alert_score(profile_id, 2)
    print("Monotonic constraint enforced")
    
    # set_cooldown (lower only)
    oracle.set_cooldown(profile_id, 30)
    
    with pytest.raises(Exception, match="may only be lowered"):
        oracle.set_cooldown(profile_id, 120)
    
    # set_active
    oracle.set_active(profile_id, False)
    state = oracle.view().get_profile(profile_id)
    assert state["active"] is False
    assert state["reliable"] is False
    
    oracle.set_active(profile_id, True)
    
    # unsubscribe
    oracle.unsubscribe(profile_id)
    
    # profile_count
    count = oracle.view().profile_count()
    assert count >= 1
    
    print("✓ All public surface methods exercised")


@pytest.mark.integration
def test_double_subscribe_refused(deploy_contract, test_account):
    """Subscribing twice is refused."""
    oracle = deploy_contract("contracts/reputation_oracle.py")
    profile_id = oracle.create_profile(
        entity_name="DoubleSubTest",
        url="https://example.com/",
        criteria="Test",
    )
    
    oracle.subscribe(profile_id, alert_below=3)
    
    with pytest.raises(Exception, match="already subscribed"):
        oracle.subscribe(profile_id, alert_below=4)
    
    print("✓ Double subscribe refused")


@pytest.mark.integration
def test_paused_profile_assess_refused(deploy_contract, test_account):
    """Assessing a paused profile is refused."""
    oracle = deploy_contract("contracts/reputation_oracle.py")
    profile_id = oracle.create_profile(
        entity_name="PausedTest",
        url="https://example.com/",
        criteria="Test",
        cooldown_seconds=0,
    )
    
    oracle.set_active(profile_id, False)
    
    with pytest.raises(Exception, match="paused"):
        oracle.assess(profile_id)
    
    print("✓ Paused profile assessment refused")
