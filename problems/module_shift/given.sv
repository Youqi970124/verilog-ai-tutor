module my_dff(input clk, input d, output logic q);
  always_ff @(posedge clk) q <= d;
endmodule
