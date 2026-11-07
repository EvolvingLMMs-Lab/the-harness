"""What the local-models package adds to the session host and the core (package.toml
[provides] host; harness/extensions.py): the deploy the core resolves agents against
(deploys: load_deploy, automatic, client_config), downloads (a benchmark's assets), the
doctor of a deploy, and installing services by name."""

from harness_local_models import deploy as deploys  # noqa: F401
from harness_local_models.provision import install as install_services  # noqa: F401
from harness_local_models.tools import doctor, download  # noqa: F401
