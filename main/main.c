#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "wifi.h"
#include "shell.h"
#include "relay.h"
#include "cloud_client.h"

static const char *TAG = "main";

static const char *reset_reason_to_string(esp_reset_reason_t reason) {
    switch (reason) {
        case ESP_RST_POWERON:
            return "power-on";
        case ESP_RST_EXT:
            return "external";
        case ESP_RST_SW:
            return "software";
        case ESP_RST_PANIC:
            return "panic";
        case ESP_RST_INT_WDT:
            return "interrupt-wdt";
        case ESP_RST_TASK_WDT:
            return "task-wdt";
        case ESP_RST_WDT:
            return "other-wdt";
        case ESP_RST_DEEPSLEEP:
            return "deep-sleep";
        case ESP_RST_BROWNOUT:
            return "brownout";
        case ESP_RST_SDIO:
            return "sdio";
        default:
            return "unknown";
    }
}

void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(relay_init());

    ESP_LOGI(
        TAG,
        "boot ok: reset=%s relay=%s free_heap=%u",
        reset_reason_to_string(esp_reset_reason()),
        relay_is_on_state() ? "on" : "off",
        (unsigned int)esp_get_free_heap_size()
    );

    wifi_start_sta(WIFI_SSID, WIFI_PASSWORD);
    shell_start();
    ESP_ERROR_CHECK(cloud_start_heartbeat());

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}