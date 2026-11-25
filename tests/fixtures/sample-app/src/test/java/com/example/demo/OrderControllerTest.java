package com.example.demo;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.model;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.view;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(OrderController.class)
@DisplayName("S01 注文登録")
class OrderControllerTest {

    @Autowired
    private MockMvc mvc;

    @Test
    @DisplayName("名前が空白のとき、422 とフォームのフラグメントを返す")
    void blankNameReturns422WithFormFragment() throws Exception {
        mvc.perform(post("/orders").param("name", " "))
                .andExpect(status().is(422))
                .andExpect(view().name("fragments/order-form"))
                .andExpect(model().attributeExists("error"));
    }

    @Test
    @DisplayName("名前を入力すると、登録結果のフラグメントに名前を表示する")
    void validNameRendersResultFragment() throws Exception {
        mvc.perform(post("/orders").param("name", "太郎"))
                .andExpect(status().isOk())
                .andExpect(view().name("fragments/order-result"))
                .andExpect(model().attribute("name", "太郎"));
    }
}
