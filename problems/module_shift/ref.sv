module RefModule(input clk, input d, output q);
  logic [2:0] shift_reg;
  always_ff @(posedge clk) shift_reg <= {shift_reg[1:0], d};
  assign q = shift_reg[2];
endmodule
