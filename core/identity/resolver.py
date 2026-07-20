from __future__ import annotations


class IdentityResolver:
    def __init__(self, repository, *, enabled: bool) -> None:
        self.repository = repository
        self.enabled = enabled

    @classmethod
    def from_feature_flags(cls, repository, feature_flags):
        return cls(
            repository,
            enabled=feature_flags.is_enabled("identity_contract_v1"),
        )

    def resolve_message(self, message):
        if not self.enabled:
            return message
        identity = self.repository.resolve(
            message.channel or message.source,
            message.channel_account_id or str(message.user_id),
        )
        message.actor_id = identity.actor_id
        message.channel = identity.channel
        message.channel_account_id = identity.channel_account_id
        return message
