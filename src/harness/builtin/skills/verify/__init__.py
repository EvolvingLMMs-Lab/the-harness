"""The success verifier, asked from inside a program."""


from harness.sdk import control


class Verify:
    def verify(self, claim, cameras=None):
        """Ask the success verifier whether `claim` holds in the current camera views.
        The verifier gets the instructions of this session's embodiment kind. Returns
        (holds, answer): holds is True for yes, False for no, None when the verifier is
        disabled in this configuration."""
        if control.host_thoughts:
            try:
                evidence = self._evidence()
            except Exception:
                evidence = ""
            reply = control.think("verifier", claim=str(claim), cameras=list(cameras) if cameras is not None else None,
                                  evidence=evidence)
            if reply is None:
                return None, "The verifier is disabled in this configuration."
            answer = reply.text.strip()
            return answer.upper().startswith("YES"), answer
        if self.verifier is None:
            return None, "The verifier is disabled in this configuration."
        from harness.embodiments import KINDS

        observation = self.get_observation(cameras=cameras)
        answer = self.verifier.ask([observation.images[c] for c in observation.images],
                                   f"Claim: {claim}", system=KINDS[self.embodiment].verifier).strip()
        return answer.upper().startswith("YES"), answer
