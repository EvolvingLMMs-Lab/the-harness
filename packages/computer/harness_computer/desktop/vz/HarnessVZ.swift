// The harness's Virtualization.framework helper (harness/desktop/vm.py): runs one virtual
// machine headless, with no window and nothing on the user's screen, until its standard
// input closes; then it stops the machine and exits.
//
//   harness-vz --disk DISK --cpus N --memory MIB --width W --height H --mac MAC
//              (--macos --aux NVRAM --hardware-model BASE64 | --efi-store FILE)
//
// --macos boots a macOS guest (a Tart VM's disk.img and nvram.bin, its config.json's
// hardwareModel; a new machine identifier each run); otherwise an EFI guest (Linux) with
// a variable store of this machine's own. The network is NAT; the harness finds the guest's
// address by its MAC address in macOS's DHCP leases. It prints one JSON line:
// {"state": "running"} or {"error": "..."}.
//
// Built by the harness with swiftc and signed ad hoc with vz.entitlements
// (com.apple.security.virtualization). macOS 13 or later.

import Foundation
import Virtualization

func say(_ object: [String: String]) {
    if let data = try? JSONSerialization.data(withJSONObject: object),
       let text = String(data: data, encoding: .utf8) {
        print(text)
        fflush(stdout)
    }
}

func fail(_ message: String) -> Never {
    say(["error": message])
    exit(1)
}

var arguments: [String: String] = [:]
var flags: Set<String> = []
var index = 1
let argv = CommandLine.arguments
while index < argv.count {
    let name = argv[index]
    if name == "--macos" {
        flags.insert(name)
        index += 1
    } else if name.hasPrefix("--") && index + 1 < argv.count {
        arguments[name] = argv[index + 1]
        index += 2
    } else {
        fail("unknown argument \(name)")
    }
}

func argument(_ name: String) -> String {
    guard let value = arguments[name] else { fail("missing \(name)") }
    return value
}

func number(_ name: String) -> Int {
    guard let value = Int(argument(name)) else { fail("\(name) is a number") }
    return value
}

final class Delegate: NSObject, VZVirtualMachineDelegate {
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        exit(0)
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        say(["error": "the machine stopped: \(error.localizedDescription)"])
        exit(1)
    }
}

let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = max(number("--cpus"), VZVirtualMachineConfiguration.minimumAllowedCPUCount)
configuration.memorySize = max(UInt64(number("--memory")) * 1024 * 1024,
                               VZVirtualMachineConfiguration.minimumAllowedMemorySize)
let width = number("--width")
let height = number("--height")

if flags.contains("--macos") {
    #if arch(arm64)
    let platform = VZMacPlatformConfiguration()
    guard let model = Data(base64Encoded: argument("--hardware-model")),
          let hardware = VZMacHardwareModel(dataRepresentation: model) else {
        fail("the hardware model is not one this Mac reads")
    }
    guard hardware.isSupported else { fail("this Mac cannot run the image's hardware model") }
    platform.hardwareModel = hardware
    platform.machineIdentifier = VZMacMachineIdentifier()
    platform.auxiliaryStorage = VZMacAuxiliaryStorage(url: URL(fileURLWithPath: argument("--aux")))
    configuration.platform = platform
    configuration.bootLoader = VZMacOSBootLoader()
    let graphics = VZMacGraphicsDeviceConfiguration()
    graphics.displays = [VZMacGraphicsDisplayConfiguration(widthInPixels: width, heightInPixels: height,
                                                           pixelsPerInch: 80)]
    configuration.graphicsDevices = [graphics]
    #else
    fail("macOS guests run on Apple silicon")
    #endif
} else {
    configuration.platform = VZGenericPlatformConfiguration()
    let store = URL(fileURLWithPath: argument("--efi-store"))
    let loader = VZEFIBootLoader()
    do {
        loader.variableStore = FileManager.default.fileExists(atPath: store.path)
            ? VZEFIVariableStore(url: store)
            : try VZEFIVariableStore(creatingVariableStoreAt: store)
    } catch {
        fail("the EFI variable store: \(error.localizedDescription)")
    }
    configuration.bootLoader = loader
    let graphics = VZVirtioGraphicsDeviceConfiguration()
    graphics.scanouts = [VZVirtioGraphicsScanoutConfiguration(widthInPixels: width, heightInPixels: height)]
    configuration.graphicsDevices = [graphics]
}

do {
    let disk = try VZDiskImageStorageDeviceAttachment(url: URL(fileURLWithPath: argument("--disk")), readOnly: false)
    configuration.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: disk)]
} catch {
    fail("the disk: \(error.localizedDescription)")
}
let network = VZVirtioNetworkDeviceConfiguration()
network.attachment = VZNATNetworkDeviceAttachment()
guard let address = VZMACAddress(string: argument("--mac")) else { fail("--mac is not a MAC address") }
network.macAddress = address
configuration.networkDevices = [network]
configuration.keyboards = [VZUSBKeyboardConfiguration()]
configuration.pointingDevices = [VZUSBScreenCoordinatePointingDeviceConfiguration()]
configuration.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
configuration.memoryBalloonDevices = [VZVirtioTraditionalMemoryBalloonDeviceConfiguration()]

do {
    try configuration.validate()
} catch {
    fail("the configuration: \(error.localizedDescription)")
}

let machine = VZVirtualMachine(configuration: configuration)
let delegate = Delegate()
machine.delegate = delegate
machine.start { result in
    switch result {
    case .success:
        say(["state": "running"])
    case .failure(let error):
        fail("the machine did not start: \(error.localizedDescription)")
    }
}

// The harness's guard holds standard input: when it closes, the machine stops.
Thread.detachNewThread {
    _ = FileHandle.standardInput.readDataToEndOfFile()
    DispatchQueue.main.async {
        machine.stop { _ in exit(0) }
    }
    Thread.sleep(forTimeInterval: 10)
    exit(0)
}

dispatchMain()
