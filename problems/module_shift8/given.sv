module my_dff8(input clk, input [7:0] d, output [7:0] q);
  reg [7:0] q_reg;
  always @(posedge clk) q_reg <= d;
  assign q = q_reg;
endmodule
