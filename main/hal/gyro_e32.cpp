// Gyro aim from the Cardputer ADV's BMI270 (the original Cardputer has no
// IMU). Ported from hazke's Gyro.h: rotations are taken in "player space"
// (yaw about the real vertical, pitch = top edge toward / away), so the
// holding angle doesn't matter; the vertical comes from a complementary
// filter on the accelerometer and gyro drift is tracked while the device is
// still. Turning the Cardputer turns the view (times the turn speed); tipping
// it looks up / down. The gyro key (alt) pauses it to re-centre your hands,
// or with "hold to aim" is the only time it aims. Options > Gyro Aim sets it
// all (saved in NVS); g toggles it.
#include "hal.h"

#include <M5Unified.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

extern "C" {
#include "doomdef.h"    // VIEW_FOCAL_Y
}

namespace {

// Default: on, both speeds 5 = 2.5 view degrees per device degree (1:1
// feels sluggish on a small screen), hold pauses.
hal_gyro_config_t cfg = { 1, 5, 5, 0, 0, 0 };

// Device frame: X right across the screen, Y up the screen, Z out of it.
const int   Map[3]  = { 0, 1, 2 };
const float Sign[3] = { 1.0f, 1.0f, 1.0f };

const float DegToRad = 0.017453293f;
const float Tau      = 0.4f;               // s, accel pull on the vertical
const float ShakeG   = 0.25f;              // skip accel off 1 g by more
const float StillRad = 2.0f * DegToRad;    // below this the device is "still"
const float BiasTau  = 2.0f;               // s, drift tracking while still
const float DeadRad  = 0.5f * DegToRad;    // per-axis noise floor

const unsigned SettingsKey = 0x6763;       // NVS slot for cfg ("gc")
const uint8_t  SettingsVersion = 1;

bool ready;
int64_t last_us;
float acc[3], gyr[3], bias[3];
float up[3] = { 0, 0, 1 };
float turn_frac, look_frac;                // sub-unit remainders

bool available() { return ready && M5.Imu.isEnabled(); }

bool sample()
{
    if(!available() || !M5.Imu.update())
        return false;

    const auto& d = M5.Imu.getImuData();

    for(int i = 0; i < 3; i++)
    {
        acc[i] = Sign[i] * d.accel.value[Map[i]];
        gyr[i] = Sign[i] * d.gyro.value[Map[i]] * DegToRad;
    }

    return true;
}

float accNorm() { return sqrtf(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2]); }

void level()
{
    float n = accNorm();

    if(n > 0.1f)
        for(int i = 0; i < 3; i++)
            up[i] = acc[i] / n;
}

void update(float dt)
{
    float n = accNorm();
    float w[3];
    bool still = true;

    for(int i = 0; i < 3; i++)
    {
        w[i] = gyr[i] - bias[i];

        if(fabsf(w[i]) > StillRad)
            still = false;
    }

    if(still)
    {
        float k = dt / (BiasTau + dt);

        for(int i = 0; i < 3; i++)
            bias[i] += w[i] * k;
    }

    // A world-fixed vector seen from the rotating body: dv/dt = v x w.
    float v0 = up[0], v1 = up[1], v2 = up[2];
    up[0] += (v1 * w[2] - v2 * w[1]) * dt;
    up[1] += (v2 * w[0] - v0 * w[2]) * dt;
    up[2] += (v0 * w[1] - v1 * w[0]) * dt;

    if(fabsf(n - 1.0f) < ShakeG)
    {
        float k = dt / (Tau + dt);

        for(int i = 0; i < 3; i++)
            up[i] += (acc[i] / n - up[i]) * k;
    }

    float len = sqrtf(up[0] * up[0] + up[1] * up[1] + up[2] * up[2]);

    if(len > 1e-3f)
        for(int i = 0; i < 3; i++)
            up[i] /= len;
}

float deadband(float v)
{
    if(v > DeadRad) return v - DeadRad;
    if(v < -DeadRad) return v + DeadRad;
    return 0.0f;
}

// Player-space rates, rad/s, drift removed: pitch (+ top edge toward the
// player = look up), yaw (+ right).
void playerRates(float& pitch, float& yaw)
{
    float w[3];

    for(int i = 0; i < 3; i++)
        w[i] = gyr[i] - bias[i];

    float d  = up[0];
    float r0 = 1.0f - d * up[0], r1 = -d * up[1], r2 = -d * up[2];
    float rl = sqrtf(r0 * r0 + r1 * r1 + r2 * r2);

    if(rl < 1e-3f) { r0 = 1.0f; r1 = r2 = 0.0f; rl = 1.0f; }

    r0 /= rl; r1 /= rl; r2 /= rl;

    pitch =  (w[0] * r0    + w[1] * r1    + w[2] * r2);
    yaw   = -(w[0] * up[0] + w[1] * up[1] + w[2] * up[2]);
}

} // namespace

void HAL_GyroInit(void)
{
    ready = M5.Imu.isEnabled();

    uint8_t saved[1 + sizeof(cfg)] = { 0 };
    HAL_SettingsLoad(saved, sizeof(saved), SettingsKey);

    if(saved[0] == SettingsVersion)
    {
        memcpy(&cfg, saved + 1, sizeof(cfg));
        if(cfg.turn > HAL_GYRO_STEPS) cfg.turn = 5;
        if(cfg.look > HAL_GYRO_STEPS) cfg.look = 5;
    }

    if(sample())
        level();

    last_us = esp_timer_get_time();
    printf("Gyro aim: %s, %s, turn %d look %d\n", available() ? "BMI270" : "no IMU",
           cfg.on ? "on" : "off", cfg.turn, cfg.look);
}

int HAL_GyroAvailable(void)
{
    return available();
}

hal_gyro_config_t* HAL_GyroConfig(void)
{
    return &cfg;
}

void HAL_GyroSaveConfig(void)
{
    uint8_t saved[1 + sizeof(cfg)];

    saved[0] = SettingsVersion;
    memcpy(saved + 1, &cfg, sizeof(cfg));
    HAL_SettingsSave(saved, sizeof(saved), SettingsKey);
    turn_frac = look_frac = 0;
}

// Average the gyro over ~0.4 s as its zero point; fails (keeps the old
// one) if the device moved meanwhile.
int HAL_GyroCalibrate(void)
{
    if(!available())
        return 0;

    const int want = 80;
    float sum[3] = { 0, 0, 0 }, lo[3], hi[3];
    int n = 0;
    int64_t until = esp_timer_get_time() + 1000000;

    while(n < want && esp_timer_get_time() < until)
    {
        if(!sample())
        {
            vTaskDelay(1);
            continue;
        }

        for(int i = 0; i < 3; i++)
        {
            sum[i] += gyr[i];
            lo[i] = n ? fminf(lo[i], gyr[i]) : gyr[i];
            hi[i] = n ? fmaxf(hi[i], gyr[i]) : gyr[i];
        }
        n++;
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    if(n < want / 2)
        return 0;

    for(int i = 0; i < 3; i++)
        if(hi[i] - lo[i] > 3.0f * DegToRad)
            return 0;

    for(int i = 0; i < 3; i++)
        bias[i] = sum[i] / n;

    level();
    turn_frac = look_frac = 0;
    last_us = esp_timer_get_time();
    return 1;
}

void HAL_GyroRead(int* angleturn, int* look, int held)
{
    *angleturn = 0;
    *look = 0;

    if(!sample())
        return;

    int64_t now = esp_timer_get_time();
    float dt = (now - last_us) * 1e-6f;
    last_us = now;

    if(dt <= 0.0f || dt > 0.25f)    // first read, or after a pause/menu
    {
        level();
        return;
    }

    update(dt);

    if(!cfg.on || (cfg.hold_aims ? !held : held))
    {
        turn_frac = look_frac = 0;
        return;
    }

    float pitch, yaw;
    playerRates(pitch, yaw);

    const float turn_gain = cfg.turn * 0.5f * (cfg.invert_turn ? -1.0f : 1.0f);
    const float look_gain = cfg.look * 0.5f * (cfg.invert_look ? -1.0f : 1.0f);

    // yaw: + right; Doom angleturn: + left, 65536 = full turn
    turn_frac += -deadband(yaw) * turn_gain * dt * (65536.0f / (2.0f * 3.14159265f));
    // pitch: + up; look rows at the view's vertical focal length
    look_frac += deadband(pitch) * look_gain * dt * VIEW_FOCAL_Y;

    *angleturn = (int)turn_frac;
    turn_frac -= *angleturn;
    *look = (int)look_frac;
    look_frac -= *look;
}
