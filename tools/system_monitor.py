# ==========================================================
# JARVIS — System Monitor
# Real-time CPU, RAM, and GPU telemetry.
# ==========================================================

import psutil

# Initialize CPU percent tracking (first call returns 0.0)
psutil.cpu_percent()

# ----------------------------------------------------------
# GPU support via pynvml (NVIDIA only)
# ----------------------------------------------------------
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU_AVAILABLE = True
except Exception:
    _GPU_AVAILABLE = False


def get_cpu_stats():
    """Return CPU usage percentage instantly without blocking."""
    return psutil.cpu_percent(interval=None)


def get_ram_stats():
    """Return RAM usage as a dict."""
    mem = psutil.virtual_memory()
    return {
        "used_gb": round(mem.used / (1024 ** 3), 1),
        "total_gb": round(mem.total / (1024 ** 3), 1),
        "percent": mem.percent,
    }


def get_gpu_stats():
    """Return GPU stats dict, or None if no NVIDIA GPU."""
    if not _GPU_AVAILABLE:
        return None

    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")

        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        temp = pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        )

        return {
            "name": name,
            "utilization_percent": util.gpu,
            "vram_used_gb": round(mem_info.used / (1024 ** 3), 1),
            "vram_total_gb": round(mem_info.total / (1024 ** 3), 1),
            "temperature_c": temp,
        }
    except Exception as e:
        return {"error": str(e)}


def get_system_summary():
    """Return an ultra-clear system status string for the LLM.

    The format is designed so the LLM can read it nearly verbatim
    without needing to reinterpret or rephrase the data.
    """
    lines = []

    # CPU — exact format: "X% CPU is being utilized"
    cpu = get_cpu_stats()
    lines.append(f"CPU usage: {cpu}% of CPU is being utilized")

    # RAM — exact format: "X GB of RAM is utilized out of Y GB"
    ram = get_ram_stats()
    lines.append(
        f"RAM usage: {ram['used_gb']} GB of RAM is utilized out of {ram['total_gb']} GB"
    )

    # GPU — exact format: name, utilization %, VRAM used/total
    gpu = get_gpu_stats()
    if gpu is None:
        lines.append("GPU: No NVIDIA GPU detected")
    elif "error" in gpu:
        lines.append(f"GPU: Error reading stats — {gpu['error']}")
    else:
        lines.append(
            f"Graphics card: {gpu['name']}, "
            f"{gpu['utilization_percent']}% GPU is being utilized, "
            f"{gpu['vram_used_gb']} GB VRAM is being used out of {gpu['vram_total_gb']} GB, "
            f"temperature is {gpu['temperature_c']} degrees celsius"
        )

    return "\n".join(lines)


# ----------------------------------------------------------
# Quick self-test
# ----------------------------------------------------------
if __name__ == "__main__":
    print("=== JARVIS System Monitor ===")
    print(get_system_summary())
