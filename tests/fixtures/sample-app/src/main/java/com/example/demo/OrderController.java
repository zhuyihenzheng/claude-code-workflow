package com.example.demo;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

/** Full page and HTMX fragment use separate JSP views; validation errors return 422 + form fragment. */
@Controller
public class OrderController {

    @GetMapping("/orders/new")
    public String newOrder() {
        return "orders/new";
    }

    @PostMapping("/orders")
    public String create(@RequestParam(defaultValue = "") String name, Model model, HttpServletResponse response) {
        model.addAttribute("name", name);
        if (name.isBlank()) {
            response.setStatus(HttpStatus.UNPROCESSABLE_ENTITY.value());
            model.addAttribute("error", "名前を入力してください");
            return "fragments/order-form";
        }
        return "fragments/order-result";
    }
}
