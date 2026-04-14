#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#include "esp_crt_bundle.h"
#include "esp_err.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "cloud_client.h"
#include "wifi.h"

#ifndef CLOUD_BASE_URL
#define CLOUD_BASE_URL ""
#endif

#define HEARTBEAT_INTERVAL_MS 30000
#define HTTP_RESPONSE_BUFFER_SIZE 2048
#define HEARTBEAT_TASK_STACK_SIZE 6144

static const char *TAG = "cloud_client";

static esp_err_t http_event_handler(esp_http_client_event_t *evt) {
    char **response_buffer = (char **)evt->user_data;
    if (!response_buffer || !*response_buffer) {
        return ESP_OK;
    }

    switch (evt->event_id) {
        case HTTP_EVENT_ON_DATA:
            if (evt->data && evt->data_len > 0) {
                size_t current_len = strlen(*response_buffer);
                size_t available = HTTP_RESPONSE_BUFFER_SIZE - current_len - 1;
                if (available > 0) {
                    size_t to_copy = evt->data_len < available ? (size_t)evt->data_len : available;
                    memcpy(*response_buffer + current_len, evt->data, to_copy);
                    (*response_buffer)[current_len + to_copy] = '\0';
                }
            }
            break;
        default:
            break;
    }

    return ESP_OK;
}

static bool get_device_serial(char *buffer, size_t buffer_size) {
    if (!buffer || buffer_size < 13) {
        return false;
    }

    uint8_t mac[6] = {0};
    if (esp_efuse_mac_get_default(mac) != ESP_OK) {
        return false;
    }

    snprintf(
        buffer,
        buffer_size,
        "%02X%02X%02X%02X%02X%02X",
        mac[0],
        mac[1],
        mac[2],
        mac[3],
        mac[4],
        mac[5]
    );
    return true;
}

static void heartbeat_task(void *arg) {
    (void)arg;

    char url[256];
    char serial_number[32];
    char *response_buffer = calloc(1, HTTP_RESPONSE_BUFFER_SIZE);
    if (!response_buffer) {
        ESP_LOGE(TAG, "Failed to allocate response buffer");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        if (CLOUD_BASE_URL[0] == '\0') {
            ESP_LOGW(TAG, "Cloud heartbeat disabled: missing CLOUD_BASE_URL");
            vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
            continue;
        }

        if (!get_device_serial(serial_number, sizeof(serial_number))) {
            ESP_LOGW(TAG, "Cloud heartbeat disabled: failed to read device serial");
            vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
            continue;
        }

        if (!wifi_is_connected()) {
            ESP_LOGW(TAG, "Wi-Fi disconnected, skipping heartbeat");
            vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
            continue;
        }

        snprintf(url, sizeof(url), "%s/agent/poll", CLOUD_BASE_URL);
        response_buffer[0] = '\0';

        char request_body[96];
        snprintf(request_body, sizeof(request_body), "{\"serial_number\":\"%s\"}", serial_number);

        esp_http_client_config_t config = {
            .url = url,
            .method = HTTP_METHOD_POST,
            .transport_type = HTTP_TRANSPORT_OVER_SSL,
            .crt_bundle_attach = esp_crt_bundle_attach,
            .timeout_ms = 10000,
            .event_handler = http_event_handler,
            .user_data = &response_buffer,
        };

        esp_http_client_handle_t client = esp_http_client_init(&config);
        if (!client) {
            ESP_LOGE(TAG, "Failed to initialize HTTP client");
            vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
            continue;
        }

        esp_http_client_set_header(client, "Content-Type", "application/json");
        esp_http_client_set_post_field(client, request_body, strlen(request_body));

        esp_err_t err = esp_http_client_perform(client);
        int status_code = esp_http_client_get_status_code(client);

        if (err == ESP_OK && status_code >= 200 && status_code < 300) {
            ESP_LOGI(TAG, "Heartbeat sent successfully (HTTP %d)", status_code);
            if (response_buffer[0] != '\0') {
                ESP_LOGD(TAG, "Heartbeat response: %s", response_buffer);
            }
        } else {
            ESP_LOGW(TAG, "Heartbeat failed: err=%s status=%d", esp_err_to_name(err), status_code);
        }

        esp_http_client_cleanup(client);
        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
    }
}

esp_err_t cloud_start_heartbeat(void) {
    BaseType_t task_created = xTaskCreate(
        heartbeat_task,
        "cloud_heartbeat",
        HEARTBEAT_TASK_STACK_SIZE,
        NULL,
        5,
        NULL
    );

    if (task_created != pdPASS) {
        ESP_LOGE(TAG, "Failed to create heartbeat task");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Cloud heartbeat task started");
    return ESP_OK;
}
