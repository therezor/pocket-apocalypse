# Source this to use ESP-IDF 5.5 from PlatformIO's packages with plain idf.py:
#   . tools/idf_env.sh && idf.py build
# (Same IDF/toolchain as `pio run`, without the PlatformIO SCons layer.)
PIO="$HOME/.platformio"
export IDF_PATH="$PIO/packages/framework-espidf"
export IDF_PYTHON_ENV_PATH="$HOME/.espressif/python_env/idf5.5_py3.13_env"
export PATH="$IDF_PYTHON_ENV_PATH/bin:$PIO/packages/toolchain-xtensa-esp-elf/bin:$PIO/packages/tool-cmake/bin:$PIO/packages/tool-ninja:$PIO/packages/tool-esptoolpy:$IDF_PATH/tools:$PATH"
alias idf.py="python $IDF_PATH/tools/idf.py"
