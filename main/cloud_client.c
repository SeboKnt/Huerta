#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>

#include "esp_crt_bundle.h"
#include "esp_err.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "cloud_client.h"
#include "relay.h"
#include "shell.h"
#include "wifi.h"

#ifndef CLOUD_BASE_URL
#define CLOUD_BASE_URL ""
#endif

#define HEARTBEAT_INTERVAL_MS 60000
#define KEEP_WAKE_POLL_INTERVAL_MS 5000
#define DEEP_SLEEP_WAKE_INTERVAL_SEC 30
#define IDENTIFY_CLOUD_BLINK_STEP_MS 250
#define IDENTIFY_SHELL_DURATION_MS 60000
#define IDENTIFY_SHELL_STEP_MS 80
#define HTTP_RESPONSE_BUFFER_SIZE 2048
#define HEARTBEAT_TASK_STACK_SIZE 12288
#define IDENTIFY_SEQUENCE_TASK_STACK_SIZE 20480
#define COMMAND_OUTPUT_MAX_LEN 220
#define COMMAND_ID_MAX_LEN 48

static const char *TAG = "cloud_client";
static bool shell_identify_active = false;
static volatile bool shell_identify_stop_requested = false;
static TaskHandle_t shell_identify_task_handle = NULL;
static volatile int last_cpu_load_pct = -1;

static esp_err_t http_event_handler(esp_http_client_event_t *evt);
static bool normalize_base_url(const char *input, char *output, size_t output_size);
static bool get_device_serial(char *buffer, size_t buffer_size);
static esp_err_t report_identify_state(const char *base_url, const char *serial_number, bool active);
static bool identify_uart_activity_pulse(int duration_ms, int step_ms);
static void identify_sequence_task(void *arg);
static bool response_has_identify_request(const char *response_buffer);
static int response_identify_duration(const char *response_buffer, int fallback_seconds);
static esp_err_t send_identify_done_report(const char *base_url, const char *serial_number);
static bool run_identify_signal(int duration_ms, int step_ms);
static void build_telemetry_request(char *buffer, size_t buffer_size, const char *serial_number, int cpu_load_pct);
static bool response_string_value(const char *response_buffer, const char *key, char *output, size_t output_size);
static bool response_has_deep_sleep_request(const char *response_buffer);
static bool response_has_keep_wake_request(const char *response_buffer);
static esp_err_t send_action_done_report(const char *base_url, const char *serial_number, const char *extra_fields);
static bool json_string_after_key_range(const char *start, const char *end, const char *key, char *output, size_t output_size);
static bool execute_remote_commands(const char *response_buffer, char *extra_fields, size_t extra_fields_size);
static bool append_snprintf(char *dest, size_t dest_size, const char *fmt, ...);
static void append_json_escaped(char *dest, size_t dest_size, const char *src);
static void heartbeat_task(void *arg);

static bool normalize_base_url(const char *input, char *output, size_t output_size) {
    if (!input || !output || output_size < 16) {
        return false;
    }

    output[0] = '\0';

    if (strstr(input, "http://") == input || strstr(input, "https://") == input) {
        snprintf(output, output_size, "%s", input);
    } else {
        snprintf(output, output_size, "https://%s", input);
    }

    size_t len = strlen(output);
    while (len > 0 && output[len - 1] == '/') {
        output[len - 1] = '\0';
        len--;
    }

    return output[0] != '\0';
}

static bool identify_uart_activity_pulse(int duration_ms, int step_ms) {
    if (duration_ms <= 0 || step_ms <= 0) {
        return true;
    }

    int steps = duration_ms / step_ms;
    if (steps < 1) {
        steps = 1;
    }

    for (int i = 0; i < steps; i++) {
        if (shell_identify_stop_requested) {
            return false;
        }

        if ((i % 2) == 0) {
            // Short TX burst to drive USB-UART activity LED intentionally.
            putchar('.');
            fflush(stdout);
        }
        vTaskDelay(pdMS_TO_TICKS(step_ms));
    }

    return true;
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

static bool response_has_identify_request(const char *response_buffer) {
    return response_buffer && strstr(response_buffer, "\"identify_requested\": true") != NULL;
}

static int response_identify_duration(const char *response_buffer, int fallback_seconds) {
    if (!response_buffer) {
        return fallback_seconds;
    }

    const char *marker = strstr(response_buffer, "\"identify_duration_sec\":");
    if (!marker) {
        return fallback_seconds;
    }

    marker += strlen("\"identify_duration_sec\":");
    while (*marker == ' ' || *marker == '\t') {
        marker++;
    }

    int seconds = atoi(marker);
    if (seconds < 1 || seconds > 120) {
        return fallback_seconds;
    }

    return seconds;
}

static esp_err_t report_identify_state(const char *base_url, const char *serial_number, bool active) {
    char report_url[256];
    char request_body[160];

    snprintf(report_url, sizeof(report_url), "%s/agent/report", base_url);
    snprintf(
        request_body,
        sizeof(request_body),
        "{\"serial_number\":\"%s\",\"identify_state\":%s}",
        serial_number,
        active ? "true" : "false"
    );

    esp_http_client_config_t config = {
        .url = report_url,
        .method = HTTP_METHOD_POST,
        .transport_type = HTTP_TRANSPORT_OVER_SSL,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, request_body, strlen(request_body));

    esp_err_t err = esp_http_client_perform(client);
    int status_code = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err == ESP_OK && status_code >= 200 && status_code < 300) {
        return ESP_OK;
    }

    return err != ESP_OK ? err : ESP_FAIL;
}

static esp_err_t send_identify_done_report(const char *base_url, const char *serial_number) {
    return send_action_done_report(base_url, serial_number, ",\"identify_done\":true");
}

static esp_err_t send_action_done_report(const char *base_url, const char *serial_number, const char *extra_fields) {
    char report_url[256];
    const char *fields = extra_fields ? extra_fields : "";

    snprintf(report_url, sizeof(report_url), "%s/agent/report", base_url);

    size_t needed = strlen(serial_number) + strlen(fields) + 32;
    char *request_body = calloc(needed, 1);
    if (!request_body) {
        return ESP_ERR_NO_MEM;
    }

    int written = snprintf(request_body, needed, "{\"serial_number\":\"%s\"%s}", serial_number, fields);
    if (written <= 0 || (size_t)written >= needed) {
        free(request_body);
        return ESP_FAIL;
    }

    esp_http_client_config_t config = {
        .url = report_url,
        .method = HTTP_METHOD_POST,
        .transport_type = HTTP_TRANSPORT_OVER_SSL,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, request_body, strlen(request_body));

    esp_err_t err = esp_http_client_perform(client);
    int status_code = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    free(request_body);

    if (err == ESP_OK && status_code >= 200 && status_code < 300) {
        return ESP_OK;
    }

    return err != ESP_OK ? err : ESP_FAIL;
}

static bool response_has_deep_sleep_request(const char *response_buffer) {
    return response_buffer && strstr(response_buffer, "\"deep_sleep_requested\": true") != NULL;
}

static bool response_has_keep_wake_request(const char *response_buffer) {
    if (!response_buffer) {
        return false;
    }

    return strstr(response_buffer, "\"wake_requested\": true") != NULL ||
           strstr(response_buffer, "\"terminal_session_active\": true") != NULL;
}

static bool response_string_value(const char *response_buffer, const char *key, char *output, size_t output_size) {
    if (!response_buffer || !key || !output || output_size < 2) {
        return false;
    }

    const char *marker = strstr(response_buffer, key);
    if (!marker) {
        return false;
    }

    marker += strlen(key);
    while (*marker == ' ' || *marker == '\t' || *marker == ':') {
        marker++;
    }

    if (*marker != '"') {
        return false;
    }
    marker++;

    const char *end = strchr(marker, '"');
    if (!end) {
        return false;
    }

    size_t len = (size_t)(end - marker);
    if (len >= output_size) {
        len = output_size - 1;
    }

    memcpy(output, marker, len);
    output[len] = '\0';
    return true;
}

static bool json_string_after_key_range(const char *start, const char *end, const char *key, char *output, size_t output_size) {
    if (!start || !end || !key || !output || output_size < 2 || start >= end) {
        return false;
    }

    const char *marker = strstr(start, key);
    if (!marker || marker >= end) {
        return false;
    }

    marker += strlen(key);
    while (marker < end && (*marker == ' ' || *marker == '\t' || *marker == ':')) {
        marker++;
    }
    if (marker >= end || *marker != '"') {
        return false;
    }
    marker++;

    size_t out_pos = 0;
    while (marker < end && *marker != '"' && out_pos < output_size - 1) {
        if (*marker == '\\' && marker + 1 < end) {
            marker++;
        }
        output[out_pos++] = *marker++;
    }
    output[out_pos] = '\0';

    return out_pos > 0;
}

static bool append_snprintf(char *dest, size_t dest_size, const char *fmt, ...) {
    if (!dest || dest_size < 2 || !fmt) {
        return false;
    }

    size_t used = strlen(dest);
    if (used >= dest_size - 1) {
        return false;
    }

    va_list args;
    va_start(args, fmt);
    int written = vsnprintf(dest + used, dest_size - used, fmt, args);
    va_end(args);

    if (written < 0) {
        return false;
    }

    return (size_t)written < (dest_size - used);
}

static void append_json_escaped(char *dest, size_t dest_size, const char *src) {
    if (!dest || dest_size == 0 || !src) {
        return;
    }

    size_t used = strlen(dest);
    for (const char *p = src; *p != '\0' && used < dest_size - 1; p++) {
        char ch = *p;
        if (ch == '"' || ch == '\\') {
            if (used + 2 >= dest_size) {
                break;
            }
            dest[used++] = '\\';
            dest[used++] = ch;
        } else if (ch == '\n' || ch == '\r') {
            if (used + 2 >= dest_size) {
                break;
            }
            dest[used++] = '\\';
            dest[used++] = 'n';
        } else {
            dest[used++] = ch;
        }
    }
    dest[used] = '\0';
}

static bool execute_remote_commands(const char *response_buffer, char *extra_fields, size_t extra_fields_size) {
    if (!response_buffer || !extra_fields || extra_fields_size < 16) {
        return false;
    }

    extra_fields[0] = '\0';
    const char *commands_key = strstr(response_buffer, "\"commands\"");
    if (!commands_key) {
        return false;
    }

    const char *array_start = strchr(commands_key, '[');
    if (!array_start) {
        return false;
    }
    const char *array_end = strchr(array_start, ']');
    if (!array_end || array_end <= array_start) {
        return false;
    }

    bool any = false;
    if (!append_snprintf(extra_fields, extra_fields_size, ",\"executed_command_ids\":[")) {
        return false;
    }
    bool first_id = true;
    char output_fields[768] = ",\"output_lines\":[";
    bool first_line = true;

    const char *cursor = array_start;
    while (cursor < array_end) {
        const char *obj_start = strchr(cursor, '{');
        if (!obj_start || obj_start >= array_end) {
            break;
        }
        const char *obj_end = strchr(obj_start, '}');
        if (!obj_end || obj_end > array_end) {
            break;
        }

        char cmd_id[COMMAND_ID_MAX_LEN] = {0};
        char cmd[128] = {0};
        bool has_id = json_string_after_key_range(obj_start, obj_end, "\"id\"", cmd_id, sizeof(cmd_id));
        bool has_cmd = json_string_after_key_range(obj_start, obj_end, "\"command\"", cmd, sizeof(cmd));

        if (has_id && has_cmd) {
            char cmd_output[COMMAND_OUTPUT_MAX_LEN];
            shell_execute_command(cmd, cmd_output, sizeof(cmd_output));

            if (!first_id) {
                if (!append_snprintf(extra_fields, extra_fields_size, ",")) {
                    return any;
                }
            }
            if (!append_snprintf(extra_fields, extra_fields_size, "\"%s\"", cmd_id)) {
                return any;
            }
            first_id = false;
            any = true;

            if (!first_line) {
                if (!append_snprintf(output_fields, sizeof(output_fields), ",")) {
                    return any;
                }
            }

            char line[COMMAND_OUTPUT_MAX_LEN + 64];
            size_t line_used = 0;
            const char *shown_output = cmd_output[0] ? cmd_output : "ok";

            line_used += snprintf(line + line_used, sizeof(line) - line_used, "cmd=");
            line_used += snprintf(line + line_used, sizeof(line) - line_used, "%.64s", cmd);
            line_used += snprintf(line + line_used, sizeof(line) - line_used, " -> ");
            snprintf(line + line_used, sizeof(line) - line_used, "%.160s", shown_output);

            char escaped[COMMAND_OUTPUT_MAX_LEN * 2] = {0};
            append_json_escaped(escaped, sizeof(escaped), line);
            if (!append_snprintf(output_fields, sizeof(output_fields), "\"%s\"", escaped)) {
                return any;
            }
            first_line = false;
        }

        cursor = obj_end + 1;
    }

    append_snprintf(extra_fields, extra_fields_size, "]");
    append_snprintf(output_fields, sizeof(output_fields), "]");
    append_snprintf(extra_fields, extra_fields_size, "%s", output_fields);

    return any;
}

static void build_telemetry_request(char *buffer, size_t buffer_size, const char *serial_number, int cpu_load_pct) {
    size_t ram_free_bytes = heap_caps_get_free_size(MALLOC_CAP_8BIT);
    size_t ram_min_free_bytes = heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT);
    int stack_free_words = (int)uxTaskGetStackHighWaterMark(NULL);
    int uptime_sec = (int)(esp_timer_get_time() / 1000000LL);

    snprintf(
        buffer,
        buffer_size,
        "{\"serial_number\":\"%s\",\"ram_free_bytes\":%u,\"ram_min_free_bytes\":%u,\"cpu_load_pct\":%d,\"uptime_sec\":%d,\"stack_free_words\":%d}",
        serial_number,
        (unsigned int)ram_free_bytes,
        (unsigned int)ram_min_free_bytes,
        cpu_load_pct,
        uptime_sec,
        stack_free_words
    );
}

static void identify_sequence_task(void *arg) {
    (void)arg;
    char base_url[220];
    char serial_number[32];
    bool can_sync_cloud = false;
    bool completed = false;

    shell_identify_stop_requested = false;

    ESP_LOGI(
        TAG,
        "Starting shell identify sequence over UART activity LED for %dms",
        IDENTIFY_SHELL_DURATION_MS
    );
    if (get_device_serial(serial_number, sizeof(serial_number)) &&
        wifi_is_connected() &&
        normalize_base_url(CLOUD_BASE_URL, base_url, sizeof(base_url))) {
        can_sync_cloud = true;
        esp_err_t on_err = report_identify_state(base_url, serial_number, true);
        if (on_err != ESP_OK) {
            ESP_LOGW(TAG, "Failed to sync identify on-state: %s", esp_err_to_name(on_err));
        }
    } else {
        ESP_LOGW(TAG, "Identify cloud sync unavailable: missing serial, Wi-Fi or CLOUD_BASE_URL");
    }

    completed = run_identify_signal(IDENTIFY_SHELL_DURATION_MS, IDENTIFY_SHELL_STEP_MS);

    if (can_sync_cloud) {
        if (completed) {
            esp_err_t done_err = send_identify_done_report(base_url, serial_number);
            if (done_err != ESP_OK) {
                ESP_LOGW(TAG, "Failed to report identify completion: %s", esp_err_to_name(done_err));
            }
        }

        esp_err_t off_err = report_identify_state(base_url, serial_number, false);
        if (off_err != ESP_OK) {
            ESP_LOGW(TAG, "Failed to sync identify off-state: %s", esp_err_to_name(off_err));
        }
    }

    if (!completed) {
        ESP_LOGI(TAG, "Identify stopped by user request");
    }

    shell_identify_active = false;
    shell_identify_stop_requested = false;
    shell_identify_task_handle = NULL;

    vTaskDelete(NULL);
}

static bool run_identify_signal(int duration_ms, int step_ms) {
    if (duration_ms <= 0 || step_ms <= 0) {
        return true;
    }

    return identify_uart_activity_pulse(duration_ms, step_ms);
}

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

static void heartbeat_task(void *arg) {
    (void)arg;

    char url[256];
    char base_url[220];
    char serial_number[32];
    char last_relay_debug_request_id[40] = "";
    char *response_buffer = calloc(1, HTTP_RESPONSE_BUFFER_SIZE);
    if (!response_buffer) {
        ESP_LOGE(TAG, "Failed to allocate response buffer");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        int cycle_interval_ms = HEARTBEAT_INTERVAL_MS;
        uint64_t request_start_us = esp_timer_get_time();
        bool deep_sleep_requested = false;
        bool keep_wake_requested = false;

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

        if (!normalize_base_url(CLOUD_BASE_URL, base_url, sizeof(base_url))) {
            ESP_LOGW(TAG, "Cloud heartbeat disabled: invalid CLOUD_BASE_URL");
            vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
            continue;
        }

        snprintf(url, sizeof(url), "%s/agent/poll", base_url);
        response_buffer[0] = '\0';

        char request_body[192];
        build_telemetry_request(request_body, sizeof(request_body), serial_number, last_cpu_load_pct);

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
        bool identify_requested = false;
        int identify_duration_sec = 15;

        if (err == ESP_OK && status_code >= 200 && status_code < 300) {
            ESP_LOGI(TAG, "Heartbeat sent successfully (HTTP %d)", status_code);
            if (response_buffer[0] != '\0') {
                ESP_LOGD(TAG, "Heartbeat response: %s", response_buffer);
                identify_requested = response_has_identify_request(response_buffer);
                identify_duration_sec = response_identify_duration(response_buffer, identify_duration_sec);
            }
        } else {
            ESP_LOGW(TAG, "Heartbeat failed: err=%s status=%d", esp_err_to_name(err), status_code);
        }

        esp_http_client_cleanup(client);

        if (response_buffer[0] != '\0') {
            char relay_debug_request_id[40] = "";
            char relay_debug_state[8] = "";

            deep_sleep_requested = response_has_deep_sleep_request(response_buffer);
            keep_wake_requested = response_has_keep_wake_request(response_buffer);

            response_string_value(response_buffer, "\"relay_debug_request_id\"", relay_debug_request_id, sizeof(relay_debug_request_id));
            response_string_value(response_buffer, "\"relay_debug_state\"", relay_debug_state, sizeof(relay_debug_state));
            if (relay_debug_request_id[0] != '\0' && relay_debug_state[0] != '\0' && strcmp(relay_debug_request_id, last_relay_debug_request_id) != 0) {
                esp_err_t relay_err = relay_init();
                if (relay_err == ESP_OK) {
                    if (strcmp(relay_debug_state, "on") == 0) {
                        relay_err = relay_on();
                    } else if (strcmp(relay_debug_state, "off") == 0) {
                        relay_err = relay_off();
                    }
                }

                if (relay_err != ESP_OK) {
                    ESP_LOGW(TAG, "Relay debug control failed: %s", esp_err_to_name(relay_err));
                }

                char extra_fields[96];
                snprintf(extra_fields, sizeof(extra_fields), ",\"relay_debug_done_request_id\":\"%s\"", relay_debug_request_id);
                esp_err_t report_err = send_action_done_report(base_url, serial_number, extra_fields);
                if (report_err != ESP_OK) {
                    ESP_LOGW(TAG, "Failed to report relay debug completion: %s", esp_err_to_name(report_err));
                }
                snprintf(last_relay_debug_request_id, sizeof(last_relay_debug_request_id), "%s", relay_debug_request_id);
            }

            char *command_report_fields = calloc(1024, 1);
            if (!command_report_fields) {
                ESP_LOGW(TAG, "Failed to allocate command report buffer");
            } else {
                if (execute_remote_commands(response_buffer, command_report_fields, 1024)) {
                    esp_err_t command_report_err = send_action_done_report(base_url, serial_number, command_report_fields);
                    if (command_report_err != ESP_OK) {
                        ESP_LOGW(TAG, "Failed to report command execution: %s", esp_err_to_name(command_report_err));
                    }
                }
                free(command_report_fields);
            }
        }

        uint64_t request_end_us = esp_timer_get_time();
        int active_ms = (int)((request_end_us - request_start_us) / 1000ULL);
        bool should_keep_awake = keep_wake_requested || shell_identify_active;
        int cpu_divisor_ms = should_keep_awake ? KEEP_WAKE_POLL_INTERVAL_MS : (DEEP_SLEEP_WAKE_INTERVAL_SEC * 1000);
        int cpu_load_pct = (active_ms * 100) / cpu_divisor_ms;
        if (cpu_load_pct < 0) {
            cpu_load_pct = 0;
        }
        if (cpu_load_pct > 100) {
            cpu_load_pct = 100;
        }
        last_cpu_load_pct = cpu_load_pct;

        if (identify_requested && !shell_identify_active) {
            ESP_LOGI(TAG, "Identify requested for %d seconds", identify_duration_sec);
            run_identify_signal(identify_duration_sec * 1000, IDENTIFY_CLOUD_BLINK_STEP_MS);
            esp_err_t report_err = send_identify_done_report(base_url, serial_number);
            if (report_err == ESP_OK) {
                ESP_LOGI(TAG, "Identify completion reported successfully");
            } else {
                ESP_LOGW(TAG, "Identify completion report failed: %s", esp_err_to_name(report_err));
            }
        }

        if (should_keep_awake) {
            cycle_interval_ms = KEEP_WAKE_POLL_INTERVAL_MS;
        }

        if (deep_sleep_requested || !should_keep_awake) {
            esp_err_t report_err = send_action_done_report(base_url, serial_number, ",\"deep_sleep_entering\":true");
            if (report_err != ESP_OK) {
                ESP_LOGW(TAG, "Failed to report deep sleep entering: %s", esp_err_to_name(report_err));
            }

            ESP_LOGI(TAG, "Entering deep sleep for %d seconds", DEEP_SLEEP_WAKE_INTERVAL_SEC);
            esp_sleep_enable_timer_wakeup((uint64_t)DEEP_SLEEP_WAKE_INTERVAL_SEC * 1000000ULL);
            esp_deep_sleep_start();
        }

        vTaskDelay(pdMS_TO_TICKS(cycle_interval_ms));
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

esp_err_t cloud_toggle_identify_state(void) {
    if (shell_identify_active) {
        shell_identify_stop_requested = true;
        return ESP_OK;
    }

    shell_identify_active = true;
    shell_identify_stop_requested = false;
    BaseType_t created = xTaskCreate(
        identify_sequence_task,
        "identify_seq",
        IDENTIFY_SEQUENCE_TASK_STACK_SIZE,
        NULL,
        5,
        &shell_identify_task_handle
    );

    if (created != pdPASS) {
        shell_identify_active = false;
        shell_identify_task_handle = NULL;
        ESP_LOGW(TAG, "Failed to create identify sequence task");
        return ESP_FAIL;
    }

    return ESP_OK;
}

bool cloud_is_identify_active(void) {
    return shell_identify_active;
}

int cloud_get_last_cpu_load_pct(void) {
    return last_cpu_load_pct;
}
