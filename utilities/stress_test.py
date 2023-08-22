import depthai as dai
from typing import List, Tuple, Dict
import cv2
import numpy as np
import signal

def on_exit(sig, frame):
    cv2.destroyAllWindows()
    exit(0)

signal.signal(signal.SIGINT, on_exit)

color_resolutions: Dict[dai.ColorCameraProperties.SensorResolution, Tuple[int, int]] = {
    # IMX582 cropped
    (5312, 6000): dai.ColorCameraProperties.SensorResolution.THE_5312X6000,
    (4208, 3120): dai.ColorCameraProperties.SensorResolution.THE_13_MP,  # AR214
    # IMX378, IMX477, IMX577
    (4056, 3040): dai.ColorCameraProperties.SensorResolution.THE_12_MP,
    # IMX582 with binning enabled
    (4000, 3000): dai.ColorCameraProperties.SensorResolution.THE_4000X3000,
    (3840, 2160): dai.ColorCameraProperties.SensorResolution.THE_4_K,
    (1920, 1200): dai.ColorCameraProperties.SensorResolution.THE_1200_P,  # AR0234
    (1920, 1080): dai.ColorCameraProperties.SensorResolution.THE_1080_P,
    (1440, 1080): dai.ColorCameraProperties.SensorResolution.THE_1440X1080,
    (2592, 1944): dai.ColorCameraProperties.SensorResolution.THE_5_MP,  # OV5645
    (1280, 800): dai.ColorCameraProperties.SensorResolution.THE_800_P,  # OV9782
    (1280, 720): dai.ColorCameraProperties.SensorResolution.THE_720_P,
}


def print_system_information(info: dai.SystemInformation):
    print(
        "Ddr: used / total - %.2f / %.2f MiB"
        % (info.ddrMemoryUsage.used
           / (1024.0 * 1024.0),
           info.ddrMemoryUsage.total / (1024.0 * 1024.0),)
    )
    print(
        "Cmx: used / total - %.2f / %.2f MiB"
        % (info.cmxMemoryUsage.used
           / (1024.0 * 1024.0),
           info.cmxMemoryUsage.total / (1024.0 * 1024.0),)
    )
    print(
        "LeonCss heap: used / total - %.2f / %.2f MiB"
        % (info.leonCssMemoryUsage.used
           / (1024.0 * 1024.0),
           info.leonCssMemoryUsage.total / (1024.0 * 1024.0),)
    )
    print(
        "LeonMss heap: used / total - %.2f / %.2f MiB"
        % (info.leonMssMemoryUsage.used
           / (1024.0 * 1024.0),
           info.leonMssMemoryUsage.total / (1024.0 * 1024.0),)
    )
    t = info.chipTemperature
    print(
        "Chip temperature - average: %.2f, css: %.2f, mss: %.2f, upa: %.2f, dss: %.2f"
        % (t.average,
           t.css,
           t.mss,
           t.upa,
           t.dss,)
    )
    print(
        "Cpu usage - Leon CSS: %.2f %%, Leon MSS: %.2f %%"
        % (info.leonCssCpuUsage.average
           * 100,
           info.leonMssCpuUsage.average * 100)
    )


def get_or_download_yolo_blob() -> str:
    import os
    import subprocess
    import sys

    this_file = os.path.realpath(__file__)
    this_dir = os.path.dirname(this_file)
    examples_dir = os.path.join(this_dir, "..", "examples")
    models_dir = os.path.join(examples_dir, "models")
    blob_path = os.path.join(
        models_dir, "yolo-v4-tiny-tf_openvino_2021.4_6shave.blob")
    downloader_cmd = [sys.executable, f"{examples_dir}/downloader/downloader.py", "--name", "tiny-yolo",
                      "--cache_dir", f"{examples_dir}/downloader/", "--num_attempts", "5", "-o", f"{examples_dir}/models"]
    subprocess.run(downloader_cmd, check=True)
    return blob_path


last_frame = {} # Store latest frame for each queue
jet_custom = cv2.applyColorMap(
    np.arange(256, dtype=np.uint8), cv2.COLORMAP_JET)
jet_custom[0] = [0, 0, 0]

def clamp(num, v0, v1):
    return max(v0, min(num, v1))

def stress_test(mxid: str = ""):
    dot_intensity = 500
    flood_intensity = 500
    iso = 800
    exp_time = 20000


    import time
    success, device_info = dai.Device.getDeviceByMxId(mxid)
    cam_args = []  # Device info or no args at all
    if success:
        cam_args.append(device_info)
    with dai.Device(*cam_args) as device:
        print("Setting default dot intensity to", dot_intensity)
        device.setIrLaserDotProjectorBrightness(dot_intensity)
        print("Setting default flood intensity to", flood_intensity)
        device.setIrFloodLightBrightness(flood_intensity)
        pipeline, outputs = build_pipeline(device)
        device.startPipeline(pipeline)
        start_time = time.time()
        queues = [device.getOutputQueue(name, size, False)
                  for name, size in outputs if name != "sys_log"]
        camera_control_q = device.getInputQueue("cam_control")
        sys_info_q = device.getOutputQueue("sys_log", 1, False)
        usb_speed = device.getUsbSpeed()
        while True:
            for queue in queues:
                packet = queue.tryGet()
                if packet is not None:
                    if queue.getName() == "tof":
                        frame = packet.getCvFrame()
                        frame = (frame.view(np.int16).astype(float))
                        frame = cv2.normalize(
                            frame, frame, alpha=255, beta=0, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                        frame = cv2.applyColorMap(frame, jet_custom)
                        last_frame[queue.getName()] = frame
                    elif isinstance(packet, dai.ImgFrame):
                        # Skip encoded frames as decoding is heavy on the host machine
                        if packet.getType() == dai.ImgFrame.Type.BITSTREAM:
                            continue
                        else:
                            last_frame[queue.getName()] = packet.getCvFrame()
            sys_info: dai.SystemInformation = sys_info_q.tryGet()
            if sys_info:
                print("----------------------------------------")
                print(f"[{int(time.time() - start_time)}s] Usb speed {usb_speed}")
                print("----------------------------------------")
                print_system_information(sys_info)
            for name, frame in last_frame.items():
                cv2.imshow(name, frame)

            # Parse keyboard input
            key = cv2.waitKey(1)
            if key == ord("q"):
                print("Q Pressed, exiting stress test...")
                break
            elif key == ord('a'):
                dot_intensity = clamp(dot_intensity - 100, 0, 1200)
                print("Decreasing dot intensity by 100, new value:", dot_intensity)
                device.setIrLaserDotProjectorBrightness(dot_intensity)
            elif key == ord('d'):
                dot_intensity = clamp(dot_intensity + 100, 0, 1200)
                print("Increasing dot intensity by 100, new value:", dot_intensity)
                device.setIrLaserDotProjectorBrightness(dot_intensity)
            elif key == ord('w'):
                flood_intensity = clamp(flood_intensity + 100, 0, 1500)
                print("Increasing flood intensity by 100, new value:", flood_intensity)
                device.setIrFloodLightBrightness(flood_intensity)
            elif key == ord('s'):
                flood_intensity = clamp(flood_intensity - 100, 0, 1500)
                print("Decreasing flood intensity by 100, new value:", flood_intensity)
                device.setIrFloodLightBrightness(flood_intensity)
            elif key == ord('k'):
                iso = clamp(iso - 50, 0, 1600)
                print("Decreasing iso by 50, new value:", iso)
                cam_ctrl  = dai.CameraControl()
                cam_ctrl.setManualExposure(exp_time, iso)
                camera_control_q.send(cam_ctrl)
            elif key == ord('l'):
                iso = clamp(iso + 50, 0, 1600)
                print("Increasing iso by 50, new value:", iso)
                cam_ctrl  = dai.CameraControl()
                cam_ctrl.setManualExposure(exp_time, iso)
                camera_control_q.send(cam_ctrl)
            elif key == ord('i'):
                exp_time = clamp(exp_time - 500, 0, 33000)
                print("Decreasing exposure time by 500, new value:", exp_time)
                cam_ctrl  = dai.CameraControl()
                cam_ctrl.setManualExposure(exp_time, iso)
                camera_control_q.send(cam_ctrl)
            elif key == ord('o'):
                exp_time = clamp(exp_time + 500, 0, 33000)
                print("Increasing exposure time by 500, new value:", exp_time)
                cam_ctrl  = dai.CameraControl()
                cam_ctrl.setManualExposure(exp_time, iso)
                camera_control_q.send(cam_ctrl)

RGB_FPS = 20
MONO_FPS = 20
ENCODER_FPS = 10


def build_pipeline(device: dai.Device) -> Tuple[dai.Pipeline, List[Tuple[str, int]]]:
    camera_features = device.getConnectedCameraFeatures()
    try:
        calib = device.readCalibration2()
    except:
        print("Couln't read calibration data from device, exiting...")
        exit(-1)

    eeprom = calib.getEepromData()
    left_socket = eeprom.stereoRectificationData.leftCameraSocket
    right_socket = eeprom.stereoRectificationData.rightCameraSocket
    align_socket = [
        cam.socket
        for cam in camera_features
        if cam.supportedTypes[0] == dai.CameraSensorType.COLOR
    ]
    is_align_socket_color = len(align_socket) != 0
    if not is_align_socket_color:
        print(f"No color camera found, aligning depth with {left_socket}")
        align_socket = [left_socket]
    align_socket = align_socket[0]

    xlink_outs: List[Tuple[str, int]] = []  # [(name, size), ...]

    pipeline = dai.Pipeline()
    sys_log = pipeline.createSystemLogger()
    sys_log.setRate(0.2)
    sys_log_out = pipeline.createXLinkOut()
    sys_log_out.setStreamName("sys_log")
    sys_log.out.link(sys_log_out.input)
    sys_log_out.input.setBlocking(False)
    sys_log_out.input.setQueueSize(1)

    cam_control = pipeline.createXLinkIn()
    cam_control.setStreamName("cam_control")

    left: dai.Node = None
    right: dai.Node = None
    # Used for spatial detection network (if available)
    color_cam: dai.Node = None

    n_color_cams = 0
    n_edge_detectors = 0
    MAX_EDGE_DETECTORS = 1
    for cam in camera_features:
        print(f"{cam.socket} Supported Sensor Resolutions:", [(conf.width, conf.height) for conf in cam.configs], "Supported Types:", cam.supportedTypes)
        max_sensor_size = (cam.configs[-1].width, cam.configs[-1].height)
        node = None
        cam_kind = cam.supportedTypes[0]
        if cam_kind == dai.CameraSensorType.MONO:
            mono = pipeline.createMonoCamera()
            node = mono
            mono.setBoardSocket(cam.socket)
            # Default to 400p. Video encoder crashes on Oak-D PRO if set to highest (800p)
            mono.setResolution(
                dai.MonoCameraProperties.SensorResolution.THE_400_P)
            mono.setFps(MONO_FPS)
        elif cam_kind == dai.CameraSensorType.COLOR:
            print("Camera socket:", cam.socket, "IS COLOR")
            n_color_cams += 1
            color = pipeline.createColorCamera()
            node = color
            color.setBoardSocket(cam.socket)
            resolution = color_resolutions.get(max_sensor_size, None)
            if resolution is None:
                print(
                    f"Skipping color camera on board socket {cam.socket}. Unknown resolution: {max_sensor_size}")
                continue
            color.setResolution(resolution)
            color.setFps(RGB_FPS)
            color_cam = color
            color.setPreviewSize(416, 416)
            color.setColorOrder(
                dai.ColorCameraProperties.ColorOrder.BGR)
            color.setInterleaved(False)

            xlink_preview = pipeline.createXLinkOut()
            stream_name = "preview_" + cam.socket.name
            xlink_preview.setStreamName(stream_name)
            color.preview.link(xlink_preview.input)
            xlink_outs.append((stream_name, 4))

        elif cam_kind == dai.CameraSensorType.TOF:
            xin_tof_config = pipeline.createXLinkIn()
            xin_tof_config.setStreamName("tof_config")
            tof = pipeline.create(dai.node.ToF)
            xin_tof_config.out.link(tof.inputConfig)
            cam_node = pipeline.create(dai.node.ColorCamera)
            cam_node.setFps(RGB_FPS)
            cam_node.setBoardSocket(cam.socket)
            cam_node.raw.link(tof.input)
            tof_xout = pipeline.createXLinkOut()
            tof_xout.setStreamName("tof")
            tof.depth.link(tof_xout.input)
            tofConfig = tof.initialConfig.get()
            tofConfig.depthParams.freqModUsed = dai.RawToFConfig.DepthParams.TypeFMod.MIN
            tofConfig.depthParams.avgPhaseShuffle = False
            tofConfig.depthParams.minimumAmplitude = 3.0
            tof.initialConfig.set(tofConfig)
            xlink_outs.append(("tof", 4))
            continue  # No video encoder and edge detector for TOF
        else:
            print(f"Unsupported camera type: {cam.supportedTypes[0]}")
            exit(-1)
        
        cam_control.out.link(node.inputControl)

        output = "out" if cam_kind == dai.CameraSensorType.MONO else "video"
        if cam.socket == left_socket:
            left = node
        elif cam.socket == right_socket:
            right = node

        if n_color_cams < 1:  # For hardcode max 1 color cam video encoders, to avoid out of memory errors
            video_encoder = pipeline.createVideoEncoder()
            video_encoder.setDefaultProfilePreset(
                ENCODER_FPS, dai.VideoEncoderProperties.Profile.H264_MAIN
            )
            getattr(node, output).link(video_encoder.input)
            ve_xlink = pipeline.createXLinkOut()
            stream_name = f"{cam.socket}.ve_out"
            ve_xlink.setStreamName(stream_name)
            video_encoder.bitstream.link(ve_xlink.input)
            xlink_outs.append((stream_name, 5))
        if n_edge_detectors < MAX_EDGE_DETECTORS:
            n_edge_detectors += 1
            edge_detector = pipeline.createEdgeDetector()
            if cam_kind == dai.CameraSensorType.COLOR:
                edge_detector.setMaxOutputFrameSize(8294400)
            getattr(node, output).link(edge_detector.inputImage)
            edge_detector_xlink = pipeline.createXLinkOut()
            stream_name = f"{cam.socket}.edge_detector"
            edge_detector_xlink.setStreamName(stream_name)
            edge_detector.outputImage.link(edge_detector_xlink.input)
            xlink_outs.append((stream_name, 5))

    if left and right:
        if left.getResolutionWidth() > 1280:
            print("Left camera width is greater than 1280, setting ISP scale to 2/3")
            left.setIspScale(2, 3)
        if right.getResolutionWidth() > 1280:
            print("Right camera width is greater than 1280, setting ISP scale to 2/3")
            right.setIspScale(2, 3)
        stereo = pipeline.createStereoDepth()
        output = "out" if hasattr(left, "out") else "video"
        getattr(left, output).link(stereo.left)
        getattr(right, output).link(stereo.right)
        stereo.setDefaultProfilePreset(
            dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        stereo.setOutputSize(left.getResolutionWidth(),
                             left.getResolutionHeight())
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(True)
        stereo.setDepthAlign(align_socket)

        if color_cam:
            yolo = pipeline.createYoloSpatialDetectionNetwork()
            blob_path = get_or_download_yolo_blob()
            yolo.setBlobPath(blob_path)
            yolo.setConfidenceThreshold(0.5)
            yolo.input.setBlocking(False)
            yolo.setBoundingBoxScaleFactor(0.5)
            yolo.setDepthLowerThreshold(100)
            yolo.setDepthUpperThreshold(5000)
            yolo.setNumClasses(80)
            yolo.setCoordinateSize(4)
            yolo.setAnchors(
                [10, 14, 23, 27, 37, 58, 81, 82, 135, 169, 344, 319])
            yolo.setAnchorMasks({"side26": [1, 2, 3], "side13": [3, 4, 5]})
            yolo.setIouThreshold(0.5)
            color_cam.preview.link(yolo.input)
            stereo.depth.link(yolo.inputDepth)

            xout_depth = pipeline.createXLinkOut()
            depth_q_name = "depth"
            xout_depth.setStreamName(depth_q_name)
            yolo.passthroughDepth.link(xout_depth.input)
            xlink_outs.append((depth_q_name, 4))

            xout_yolo = pipeline.createXLinkOut()
            yolo_q_name = "yolo"
            xout_yolo.setStreamName(yolo_q_name)
            yolo.out.link(xout_yolo.input)
            xlink_outs.append((yolo_q_name, 4))
        else:
            print(
                "Device doesn't have color camera, skipping spatial detection network creation...")
    elif color_cam:  # Only color camera, e.g. OAK-1: Create a YOLO
        yolo = pipeline.createYoloDetectionNetwork()
        blob_path = get_or_download_yolo_blob()
        yolo.setBlobPath(blob_path)
        yolo.setConfidenceThreshold(0.5)
        yolo.input.setBlocking(False)
        yolo.setNumClasses(80)
        yolo.setCoordinateSize(4)
        yolo.setAnchors(
            [10, 14, 23, 27, 37, 58, 81, 82, 135, 169, 344, 319])
        yolo.setAnchorMasks({"side26": [1, 2, 3], "side13": [3, 4, 5]})
        yolo.setIouThreshold(0.5)
        color_cam.preview.link(yolo.input)

        xout_yolo = pipeline.createXLinkOut()
        yolo_q_name = "yolo"
        xout_yolo.setStreamName(yolo_q_name)
        yolo.out.link(xout_yolo.input)
        xlink_outs.append((yolo_q_name, 4))
    else:
        print("Device doesn't have a stereo pair, skipping depth and spatial detection network creation...")

    print("XLINK OUTS:; ", xlink_outs)
    return (pipeline, xlink_outs)


if __name__ == "__main__":
    stress_test()
