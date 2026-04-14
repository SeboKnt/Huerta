#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "wifi.h"
#include "shell.h"
#include "cloud_client.h"

void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    wifi_start_sta(WIFI_SSID, WIFI_PASSWORD);
    shell_start();
    ESP_ERROR_CHECK(cloud_start_heartbeat());

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}