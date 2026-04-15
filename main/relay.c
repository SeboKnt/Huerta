#include <stdio.h>
#include <stdbool.h>

#include "driver/gpio.h"
#include "esp_err.h"

#include "relay.h"

#define RELAY_GPIO GPIO_NUM_23

static bool relay_ready = false;
static bool relay_is_on = false;

static esp_err_t relay_write(void) {
    int level = relay_is_on ? 0 : 1;
    return gpio_set_level(RELAY_GPIO, level);
}

esp_err_t relay_init(void) {
    if (relay_ready) {
        return ESP_OK;
    }

    gpio_config_t config = {
        .pin_bit_mask = (1ULL << RELAY_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    esp_err_t err = gpio_config(&config);
    if (err != ESP_OK) {
        return err;
    }

    relay_is_on = false;
    err = relay_write();
    if (err == ESP_OK) {
        relay_ready = true;
    }

    return err;
}

static esp_err_t relay_set(bool on) {
    esp_err_t err = relay_init();
    if (err != ESP_OK) {
        return err;
    }

    relay_is_on = on;
    return relay_write();
}

esp_err_t relay_on(void) {
    return relay_set(true);
}

esp_err_t relay_off(void) {
    return relay_set(false);
}

esp_err_t relay_toggle(void) {
    return relay_set(!relay_is_on);
}

bool relay_is_on_state(void) {
    return relay_is_on;
}

void relay_print_status(void) {
    printf("relay gpio23: %s\n", relay_is_on ? "on" : "off");
}