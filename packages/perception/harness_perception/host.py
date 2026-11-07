"""What the perception package adds to the core (package.toml [provides] host;
harness/extensions.py): the class of the model roles that answer about images (vlm,
pointer, verifier), by its import path, which the core passes to the episode's kernel
(config/agent.py image_roles). A path, not the class: NumPy loads in the kernel only."""

vision_model = "harness_perception.clients:VisionModel"
