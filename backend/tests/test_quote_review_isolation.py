from app.services.quote_service import QuoteService


def test_review_progress_is_delivered_only_to_the_owning_sse_subscriber():
    service = QuoteService()
    alice = service.subscribe(owner_id="alice")
    bob = service.subscribe(owner_id="bob")

    service.push_review_event('{"type":"delta","content":"private"}', owner_id="alice")

    assert alice.pop()["reviews"] == ['{"type":"delta","content":"private"}']
    assert bob.pop()["reviews"] == []
