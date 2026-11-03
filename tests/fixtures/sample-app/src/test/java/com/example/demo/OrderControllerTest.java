package com.example.demo;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.model;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.view;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(OrderController.class)
class OrderControllerTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void blankNameReturns422WithFormFragment() throws Exception {
        mvc.perform(post("/orders").param("name", " "))
                .andExpect(status().is(422))
                .andExpect(view().name("fragments/order-form"))
                .andExpect(model().attributeExists("error"));
    }

    @Test
    void validNameRendersResultFragment() throws Exception {
        mvc.perform(post("/orders").param("name", "太郎"))
                .andExpect(status().isOk())
                .andExpect(view().name("fragments/order-result"))
                .andExpect(model().attribute("name", "太郎"));
    }
}
