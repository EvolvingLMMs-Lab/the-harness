package harness.camera;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.ConnectScreen;
import net.minecraft.client.network.ServerInfo;

/**
 * The game window of a bot body. The body's bridge serves a game port on which this client
 * is sent everything the body is sent: it is the body's player, and the game itself shows
 * the world, the status bars, the hotbar, the inventory and every screen. All this mod does
 * is join that port once the game has finished loading.
 */
public final class Camera {
    private Camera() {
    }

    /**
     * The address joined (the launcher's own --server joins while resources still load, and the
     * game then draws a world without models).
     */
    private static final String SERVER = System.getProperty("harness.camera.server", System.getenv("HARNESS_CAMERA_SERVER"));
    private static int idleTicks;
    private static boolean joined;

    /** Once a client tick. */
    public static void tick() {
        MinecraftClient client = MinecraftClient.getInstance();
        if (joined || SERVER == null || SERVER.isEmpty()) {
            return;
        }
        // Any menu will do, not only the title: a recorder's own dialog may sit in front of it.
        if (client.getOverlay() != null || client.world != null || client.currentScreen == null
                || client.currentScreen instanceof ConnectScreen) {
            idleTicks = 0;
            return;
        }
        if (++idleTicks < 60) {
            return;
        }
        joined = true;
        client.openScreen(new ConnectScreen(client.currentScreen, client, new ServerInfo("body", SERVER, false)));
    }
}
